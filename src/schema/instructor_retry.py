"""
Instructor-based extraction with Pydantic retry loop.

On each Pydantic validation failure the specific error is fed back to the LLM
so it can self-correct. Up to MAX_RETRIES attempts; failures are logged to
REJECTED_QUEUE (default: data/rejected.jsonl) and never silently dropped.
"""
import json
import os
from datetime import datetime
from typing import List

import instructor
from openai import OpenAI

from .taxonomy import TAXONOMY, RelationType, EntityType
from .pydantic_model import ExtractionResult


# ── LLM client ────────────────────────────────────────────────────────────────

def _build_client() -> object:
    api_key  = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL")
    client   = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    return instructor.patch(client)


_CLIENT     = None
_MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o")
_MAX_TRIES  = int(os.getenv("MAX_RETRIES", "3"))
_QUEUE_PATH = os.getenv("REJECTED_QUEUE", "data/rejected.jsonl")


def _client() -> object:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = _build_client()
    return _CLIENT


# ── Taxonomy prompt block ─────────────────────────────────────────────────────

_TAXONOMY_BLOCK: str = ""

def _taxonomy_block() -> str:
    global _TAXONOMY_BLOCK
    if _TAXONOMY_BLOCK:
        return _TAXONOMY_BLOCK
    lines = ["RELATION TAXONOMY — use exactly these types, nothing else:\n"]
    for rel, entry in TAXONOMY.items():
        lines.append(f"  {rel.value}")
        lines.append(f"    Definition : {entry['definition']}")
        lines.append(f"    Example    : {entry['example']}")
        lines.append(f"    Not this   : {entry['not_this']}")
        lines.append("")
    _TAXONOMY_BLOCK = "\n".join(lines)
    return _TAXONOMY_BLOCK


# ── Extraction prompt ─────────────────────────────────────────────────────────

def _build_prompt(chunk: dict) -> List[dict]:
    text     = chunk["text"]
    section  = chunk.get("section", "unknown")
    entities = chunk.get("entities", [])
    negated  = chunk.get("negated_entities", [])

    entity_block = ""
    if entities:
        entity_block = "\nPRE-TAGGED ENTITIES FROM LAYER 4:\n" + "\n".join(
            f"  [{e['text']}] type={e.get('label', '?')}  "
            f"{'[ABSENT — context only; do not set negated=True automatically]' if e.get('negated') else ''}"
            for e in entities
        )

    negation_block = ""
    if negated:
        negation_block = (
            f"\nCONTEXT NOTE: Layer 4 marks {len(negated)} entity/entities ABSENT from the studied system: "
            + ", ".join(f"[{e['text']}]" for e in negated)
            + "\nAbsence is context, not negation. Relations involving these entities are often POSITIVE "
              "findings about what happens in their absence. "
              "Set negated=True ONLY when the text explicitly denies the relation itself "
              "(e.g. 'X does not regulate Y', 'no effect of X on Y')."
        )

    system = (
        "You are a biomedical relation extraction expert specialising in longevity and ageing research.\n\n"
        + _taxonomy_block()
        + "\nENTITY TYPE LIST:\n"
        + "\n".join(f"  {e.value}" for e in EntityType)
        + "\n\nRULES:\n"
        "1. Resolve extraction_viable FIRST. If no relation maps to the taxonomy, "
        "set extraction_viable=False and explain in reasoning. Stop there.\n"
        "2. If viable, fill all 13 fields for each relation found.\n"
        "3. reasoning must be ≥ 50 characters and must include: the chosen relation, "
        "alternatives considered, and the verbatim supporting text span.\n"
        "4. Do NOT invent relation types. If nothing fits, extraction_viable=False.\n"
        "5. species / tissue / condition / effect_size are empty strings when not mentioned.\n"
        "6. Produce one BiologicalRelation per distinct subject–relation–object triple."
    )

    user = (
        f"SECTION: {section}\n\n"
        f"TEXT:\n{text}"
        + entity_block
        + negation_block
        + "\n\nExtract all biological relations present in this text."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]


# ── Rejected queue ────────────────────────────────────────────────────────────

def _log_rejected(chunk: dict, error: str, attempts: int) -> None:
    os.makedirs(os.path.dirname(_QUEUE_PATH) or ".", exist_ok=True)
    entry = {
        "timestamp":   datetime.utcnow().isoformat(),
        "document_id": chunk.get("document_id", ""),
        "section":     chunk.get("section", ""),
        "text":        chunk.get("text", "")[:500],
        "error":       error,
        "attempts":    attempts,
    }
    with open(_QUEUE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── Main extraction function ──────────────────────────────────────────────────

def extract(chunk: dict) -> ExtractionResult:
    """Extract biological relations from one annotated chunk with Pydantic retry."""
    messages   = _build_prompt(chunk)
    last_error = ""

    for attempt in range(1, _MAX_TRIES + 1):
        try:
            result: ExtractionResult = _client().chat.completions.create(
                model=_MODEL_NAME,
                response_model=ExtractionResult,
                messages=messages,
                max_retries=1,
            )
            return result

        except Exception as e:
            last_error = str(e)
            if attempt < _MAX_TRIES:
                messages.append({
                    "role":    "assistant",
                    "content": f"[Attempt {attempt} failed]",
                })
                messages.append({
                    "role":    "user",
                    "content": (
                        f"Attempt failed: {last_error}\n"
                        "If this was a schema validation error, fix the specific field mentioned and retry. "
                        "Valid relation types: "
                        + ", ".join(r.value for r in RelationType)
                    ),
                })

    _log_rejected(chunk, last_error, _MAX_TRIES)
    return ExtractionResult(
        relations=[],
        rejected=True,
        rejection_reason=last_error,
    )


def extract_batch(chunks: list) -> List[ExtractionResult]:
    """Extract relations from a list of pre-annotated chunks."""
    return [extract(chunk) for chunk in chunks]
