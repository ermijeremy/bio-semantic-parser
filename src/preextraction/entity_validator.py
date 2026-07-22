"""
Layer 4 — Entity Validator

1. Shorten overly long entity spans that are unlikely to be meaningful relations
   (e.g. "bare-metal Tryton Side Branch (SB) Stent" → "Tryton Stent")
2. Refine entities that don't make sense as standalone concepts
   (e.g. "main branch" as ANATOMY → "coronary artery" or keep if context-dependent)

"""
from __future__ import annotations

import json
import logging
import os
import re

from src.llm_client import call_llm

_log = logging.getLogger(__name__)

# Only invoke LLM validation if entity has more than this many tokens.
_TOKEN_THRESHOLD = int(os.getenv("ENTITY_VALIDATION_TOKEN_THRESHOLD", "5"))
_BATCH_SIZE = int(os.getenv("ENTITY_VALIDATION_BATCH_SIZE", "30"))


def _word_count(text: str) -> int:
    return len(text.split())


def _needs_shortening(text: str) -> bool:
    return _word_count(text) > _TOKEN_THRESHOLD


def _validation_prompt(entities: list[dict], text: str) -> str:
    """Build a prompt that asks the LLM to shorten overly long entity spans."""
    entity_lines = []
    for e in entities:
        entity_lines.append(
            f'  text="{e["text"]}"  type={e["label"]}'
        )

    return (
        "You are a biomedical entity validator. You will receive a list of "
        "pre-tagged entities extracted from a biomedical text chunk, along with "
        "the original text for context.\n\n"
        f"Each entity in this list has more than {_TOKEN_THRESHOLD} words and may "
        "contain branding, product names, or descriptive modifiers that don't "
        "belong in a canonical biomedical entity name.\n\n"
        "For each entity, shorten it to the core biomedical concept by removing "
        "brand names, product suffixes (e.g. '™'), and descriptive modifiers that "
        "aren't part of the canonical name. If the entity is already a clean "
        "canonical name, output null (no change needed).\n\n"
        "RULES:\n"
        "- Keep the replacement SHORT (ideally 1-3 words).\n"
        "- The replacement must be a valid biomedical entity, not a phrase.\n"
        "- If you shorten an entity, you may also correct its type "
        "if the original type was clearly wrong.\n"
        "- Output ONLY a JSON array of objects. Each object has:\n"
        "  - \"original\": the exact original text\n"
        "  - \"replacement\": the shortened text, or null if no change\n"
        "  - \"new_type\": the corrected type, or null if type is unchanged\n"
        "- Do NOT output any explanation.\n\n"
        "ORIGINAL TEXT (for context):\n"
        f"{text}\n\n"
        "ENTITIES TO SHORTEN:\n"
        + "\n".join(entity_lines)
        + "\n\n"
        "Return a JSON array. Example:\n"
        '[{"original": "bare-metal Tryton Side Branch (SB) Stent", '
        '"replacement": "Tryton Stent", "new_type": null},\n'
        ' {"original": "recombinant human erythropoietin alfa injection", '
        '"replacement": "erythropoietin", "new_type": "SMALL_MOLECULE"}]'
    )


def _parse_response(raw: str) -> list[dict]:
    """Extract the JSON array from the LLM response."""
    raw = raw.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        _log.warning("[entity-validator] failed to parse LLM response as JSON")
    return []


def validate_entities(entities: list[dict], text: str) -> list[dict]:
    """Returns a new entity list with corrected text/labels."""
    
    candidates = [e for e in entities if _needs_shortening(e["text"])]

    if not candidates:
        return entities

    _log.info(
        "[entity-validator] %d entities need validation "
        "(threshold=%d words)", len(candidates), _TOKEN_THRESHOLD,
    )

    # Process in batches
    refined_map: dict[str, dict] = {}
    for i in range(0, len(candidates), _BATCH_SIZE):
        batch = candidates[i : i + _BATCH_SIZE]
        prompt = _validation_prompt(batch, text)

        raw = call_llm(
            messages=[
                {"role": "system", "content": "You are a biomedical entity validator. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            json_mode=False,
            max_tokens=4096,
        )
        updates = _parse_response(raw)
        for u in updates:
            orig = (u.get("original") or "").strip()
            repl = u.get("replacement")
            new_type = u.get("new_type")
            if orig and (repl or new_type):
                refined_map[orig] = {
                    "replacement": repl,
                    "new_type": new_type,
                }
        _log.info(
            "[entity-validator] batch %d: got %d updates from LLM",
            i // _BATCH_SIZE + 1, len(updates),
        )

    # Apply refinements
    refined_entities = []
    for e in entities:
        ref = refined_map.get(e["text"])
        if ref is None:
            refined_entities.append(e)
            continue
        new_e = e.copy()
        if ref.get("replacement"):
            new_e["text"] = ref["replacement"]
            new_e["normalized"] = ref["replacement"].lower().strip()
            _log.info(
                "[entity-validator] shortened: %r → %r",
                e["text"], ref["replacement"],
            )
        if ref.get("new_type"):
            new_e["label"] = ref["new_type"]
            _log.info(
                "[entity-validator] retyped: %r: %s → %s",
                e["text"], e["label"], ref["new_type"],
            )
        refined_entities.append(new_e)

    return refined_entities
