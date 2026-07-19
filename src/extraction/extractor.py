from __future__ import annotations
"""Layer 6 — LLM extraction engine. Builds prompts, calls Gemma, validates via Pydantic."""
import concurrent.futures
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from pydantic import ValidationError
from openai import OpenAI
import httpx

from src.schema.taxonomy import TAXONOMY, RelationType, EntityType
from src.schema.pydantic_model import BiologicalRelation, ExtractionResult

# ── Config from .env ──────────────────────────────────────────────────────────
_BASE_URL    = os.getenv("LLM_BASE_URL",    "http://localhost:11434/v1")
_API_KEY     = os.getenv("LLM_API_KEY",     "ollama")
_MODEL       = os.getenv("LLM_MODEL",       "gemma2:27b")
_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))
_MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
_QUEUE_PATH  = Path(os.getenv("REJECTED_QUEUE", "data/rejected.jsonl"))
_OUT_RESERVE      = int(os.getenv("LLM_OUTPUT_TOKENS", "2048"))
_WALL_TIMEOUT     = int(os.getenv("LLM_WALL_TIMEOUT",  "300"))
_COMPACT_TAXONOMY = os.getenv("LLM_COMPACT_TAXONOMY", "0").strip().lower() in ("1", "true", "yes")
_MAX_ENTITIES     = int(os.getenv("LLM_MAX_ENTITIES", "0"))
_CACHED_SYSTEM_PROMPT: str = ""

def _get_system_prompt() -> str:
    global _CACHED_SYSTEM_PROMPT
    if not _CACHED_SYSTEM_PROMPT:
        _CACHED_SYSTEM_PROMPT = _system_prompt()
    return _CACHED_SYSTEM_PROMPT

def _client() -> OpenAI:
    # Fresh client per call — keepalive disabled to prevent silent stale-connection hangs.
    return OpenAI(
        api_key    = _API_KEY,
        base_url   = _BASE_URL,
        http_client = httpx.Client(
            limits  = httpx.Limits(
                max_keepalive_connections = 0,
                max_connections           = 1,
            ),
            timeout = httpx.Timeout(600.0, connect=10.0),
        ),
    )


# ── JSON schema block (given to LLM in system prompt) ────────────────────────

_RELATION_VALUES = " | ".join(r.value for r in RelationType)
_ENTITY_VALUES   = " | ".join(e.value for e in EntityType)

_JSON_SCHEMA = """\
Required JSON output format — return ONLY this structure, nothing else:
{
  "relations": [
    {
      "extraction_viable": true,
      "subject_name":  "<verbatim entity text>",
      "subject_type":  "<EntityType value>",
      "relation":      "<RelationType value>",
      "object_name":   "<verbatim entity text>",
      "object_type":   "<EntityType value>",
      "negated":       false,
      "confidence":    0.0,
      "reasoning":     "<min 50 chars — why this relation type, alternatives considered, verbatim supporting text>",
      "species":       "<e.g. Homo sapiens — empty string if not stated>",
      "tissue":        "<e.g. hippocampus — empty string if not stated>",
      "condition":     "<e.g. caloric restriction — empty string if not stated>",
      "effect_size":   "<e.g. 40% reduction — empty string if not stated>"
    }
  ]
}

If no relation can be extracted, return:
{
  "relations": [
    {
      "extraction_viable": false,
      "subject_name": "", "subject_type": "OTHER", "relation": null,
      "object_name": "", "object_type": "OTHER", "negated": false,
      "confidence": 0.0, "reasoning": "<explain why no relation found — min 50 chars>",
      "species": "", "tissue": "", "condition": "", "effect_size": ""
    }
  ]
}"""


# ── Taxonomy block ────────────────────────────────────────────────────────────

def _taxonomy_block() -> str:
    lines = ["RELATION TYPES — use ONLY values from this list:\n"]
    for rel, entry in TAXONOMY.items():
        if _COMPACT_TAXONOMY:
            not_this = entry.get("not_this", "")
            not_clause = f" [NOT: {not_this}]" if not_this else ""
            lines.append(f"  {rel.value}: {entry['definition']}{not_clause}")
        else:
            lines.append(
                f"  {rel.value}\n"
                f"    → {entry['definition']}\n"
                f"    EXAMPLE: {entry['example']}\n"
                f"    NOT THIS: {entry['not_this']}\n"
            )
    return "\n".join(lines)


# ── Full system prompt ────────────────────────────────────────────────────────
# Shape the LLM's strategy before it starts —
# how to think about the task, not just what to put in each field.
def _system_prompt() -> str:
    return (
        "You are a biomedical relation extraction expert.\n"
        "Extract biological relations from text and return ONLY valid JSON.\n\n"
        + _taxonomy_block()
        + f"\nVALID relation values: {_RELATION_VALUES}\n"
        + f"VALID entity type values: {_ENTITY_VALUES}\n\n"
        + _JSON_SCHEMA
        + "\n\nRULES:\n"
        "1. Decide extraction_viable FIRST — true if a valid relation exists, false otherwise. "
        "   If false, stop: leave all other fields at defaults.\n"
        "2. relation MUST be one of the VALID relation values above — never invent a new type. "
        "   The relation types are the formal predicates from Biolink Model, Hetionet, and OpenBioLink. "
        "   These schemas are domain-agnostic: their definitions apply equally to molecular biology, "
        "   clinical medicine, epidemiology, and outcomes research. "
        "   When selecting a relation type, reason from the formal definition alone — "
        "   the example is one illustrative instance, not a restriction on subject or domain. "
        "   The not_this field distinguishes between similar relation types; it does not restrict "
        "   the domain, subject type, or context in which the relation can apply. "
        "   Only set extraction_viable=false if the formal definition genuinely does not apply "
        "   to the relation described in the text, after reading all definitions carefully.\n"
        "3. subject_name and object_name MUST come from the PRE-TAGGED ENTITIES list. "
        "   Only entities that appear in the PRE-TAGGED ENTITIES list are valid subjects or objects. "
        "   If a relation involves entities NOT in the pre-tagged list, set extraction_viable=false. "
        "   Use the exact verbatim text as it appears in the list. "
        "   Do NOT add species prefixes ('mammalian', 'human') unless the text says so.\n"
        "4. Produce exactly one JSON object per distinct subject–relation–object triple. "
        "   Do not merge different triples into one.\n"
        "5. Return ONLY the JSON — no explanation, no markdown fences, no extra text."
    )


def _user_message(chunk: dict) -> str:
    text     = chunk.get("text", "")
    section  = chunk.get("section", "unknown")
    entities = chunk.get("entities", [])
    negated  = chunk.get("negated_entities", [])

    if _MAX_ENTITIES > 0 and len(entities) > _MAX_ENTITIES:
        entities = entities[:_MAX_ENTITIES]

    entity_block = ""
    if entities:
        entity_block = "\n\nPRE-TAGGED ENTITIES FROM LAYER 4:\n" + "\n".join(
            f"  [{e['text']}]  type={e.get('label', '?')}  "
            f"{'[NEGATED — set negated=true for any relation involving this entity]' if e.get('negated') else ''}"
            for e in entities
        )

    negation_block = ""
    if negated:
        negation_block = (
            f"\n\nNEGATION FLAG: Layer 4 detected negation in this chunk. "
            f"The following entities are ABSENT: "
            + ", ".join(f"[{e['text']}]" for e in negated)
            + "\nSet negated=true for any relation involving these entities."
        )

    return (
        f"SECTION: {section}\n\n"
        f"TEXT:\n{text}"
        + entity_block
        + negation_block
        + "\n\nExtract ALL biological relations from the text above — be exhaustive, "
          "do not skip any. Return JSON only."
    )


# ── JSON parser ───────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw)
    return json.loads(raw.strip())


# ── Rejected queue ────────────────────────────────────────────────────────────

def _log_rejected(chunk: dict, error: str, attempts: int) -> None:
    _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "document_id": chunk.get("document_id", ""),
        "section":     chunk.get("section", ""),
        "text":        chunk.get("text", "")[:500],
        "error":       error,
        "attempts":    attempts,
        "model":       _MODEL,
        "base_url":    _BASE_URL,
    }
    with open(_QUEUE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_truncation_error(error: str) -> bool:
    """Return True if the error is a JSON truncation (token limit hit mid-response)."""
    truncation_signals = [
        "Unterminated string", "Expecting ',' delimiter",
        "Expecting property name", "Expecting value", "Extra data",
    ]
    return any(s.lower() in error.lower() for s in truncation_signals)

def _split_chunk(chunk: dict) -> list:
    """Split a chunk's text in half at a sentence boundary, returning two sub-chunks (with other metadata)."""
    text = chunk.get("text", "")
    sentences = text.split(". ")
    mid = len(sentences) // 2
    half1 = ". ".join(sentences[:mid]) + ("." if sentences[:mid] else "")
    half2 = ". ".join(sentences[mid:])
    base = {k: v for k, v in chunk.items() if k != "text"}
    return [
        {**base, "text": half1, "_sub_chunk": "1/2"},
        {**base, "text": half2, "_sub_chunk": "2/2"},
    ]


# ── Core extraction ───────────────────────────────────────────────────────────

def extract(chunk: dict, _depth: int = 0) -> ExtractionResult:
    """
    Extract biological relations from one annotated chunk.

    If the LLM response is truncated (token limit hit mid-JSON), the chunk
    is automatically split in half and each half is extracted separately.
    """
    system  = _get_system_prompt()
    user    = _user_message(chunk)
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]

    last_error = ""
    last_raw   = ""

    # Health-check once before the retry loop
    _server_root = _BASE_URL.rstrip("/").removesuffix("v1").rstrip("/")
    try:
        httpx.get(f"{_server_root}/health", timeout=8.0)
    except Exception:
        try:
            httpx.get(f"{_server_root}/v1/models",
                      headers={"Authorization": f"Bearer {_API_KEY}"}, timeout=8.0)
        except Exception as _he:
            raise ConnectionError(f"vLLM server unreachable at {_BASE_URL} — {_he}")

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            # Pass messages explicitly to avoid closure-capture-by-reference bug
            def _call(msgs=messages):
                return _client().chat.completions.create(
                    model           = _MODEL,
                    messages        = msgs,
                    temperature     = _TEMPERATURE,
                    max_tokens      = _OUT_RESERVE,
                    response_format = {"type": "json_object"},
                )

            # Wall-clock timeout via ThreadPoolExecutor — fires even when the
            # server sends TCP keepalive bytes (unlike httpx read timeout).
            _pool   = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            _future = _pool.submit(_call)
            try:
                response = _future.result(timeout=_WALL_TIMEOUT)
                last_raw = response.choices[0].message.content or ""
            except concurrent.futures.TimeoutError:
                _pool.shutdown(wait=False)
                raise TimeoutError(
                    f"LLM did not respond within {_WALL_TIMEOUT}s — server overloaded"
                )
            finally:
                _pool.shutdown(wait=False)

            data          = _parse_json(last_raw)
            raw_relations = data.get("relations", [data])
            relations     = [BiologicalRelation(**r) for r in raw_relations]
            return ExtractionResult(relations=relations)

        except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as exc:
            last_error = str(exc)

            if _is_truncation_error(last_error) and _depth == 0:
                sub_chunks    = _split_chunk(chunk)
                all_relations = []
                for sc in sub_chunks:
                    sub_result = extract(sc, _depth=1)
                    all_relations.extend(sub_result.relations)
                seen, unique = set(), []
                for r in all_relations:
                    key = (getattr(r, "subject_name", "").lower(),
                           r.relation.value if r.relation else "",
                           getattr(r, "object_name",  "").lower())
                    if key not in seen:
                        seen.add(key)
                        unique.append(r)
                if unique:
                    return ExtractionResult(relations=unique)

            if attempt < _MAX_RETRIES:
                messages.append({"role": "assistant", "content": last_raw})
                messages.append({
                    "role":    "user",
                    "content": (
                        f"Your output failed validation (attempt {attempt}/{_MAX_RETRIES}).\n"
                        f"Error: {last_error}\n\n"
                        f"Valid relation values: {_RELATION_VALUES}\n"
                        f"Valid entity type values: {_ENTITY_VALUES}\n\n"
                        "Fix the specific field mentioned and return corrected JSON only."
                    ),
                })

        except TimeoutError as exc:
            last_error = str(exc)
            if attempt < _MAX_RETRIES:
                time.sleep(5 * attempt)
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ]
            else:
                break

        except Exception as exc:
            last_error = str(exc)
            break

    _log_rejected(chunk, last_error, _MAX_RETRIES)
    return ExtractionResult(
        relations        = [],
        rejected         = True,
        rejection_reason = last_error,
    )


def extract_batch(chunks: list) -> list:
    """
    Extract relations from a list of annotated chunks in parallel.

    Chunks are processed concurrently up to LLM_CHUNK_CONCURRENCY workers
    (default 4, capped by the global LLM_GLOBAL_CONCURRENCY semaphore).

    Saves a per-chunk progress file so the batch can resume from cached
    results if the pipeline restarts mid-run.

    Progress file: data/checkpoints/{doc_id}_layer6_progress.jsonl
    Delete it to force a full re-extraction.
    """
    import json as _json
    import threading as _threading
    import concurrent.futures as _cf

    _WORKERS = int(os.getenv("LLM_CHUNK_CONCURRENCY", "4"))

    doc_id   = (chunks[0].get("document_id", "") if chunks else "")
    _safe_id = doc_id.replace("/", "_").replace(":", "_") if doc_id else "unknown"
    _ckpt_dir = Path(os.getenv("CHECKPOINTS_DIR", "data/checkpoints"))
    _ckpt_dir.mkdir(parents=True, exist_ok=True)
    _progress_path = _ckpt_dir / f"{_safe_id}_layer6_progress.jsonl"
    _file_lock = _threading.Lock()
    _completed: dict = {}
    if _progress_path.exists():
        try:
            for line in _progress_path.read_text(encoding="utf-8").splitlines():
                entry = _json.loads(line)
                _completed[entry["chunk_index"]] = entry["result"]
        except Exception:
            pass

    def _process_one(args):
        i, chunk = args
        chunk_index = chunk.get("chunk_index", i)

        if chunk_index in _completed:
            cached    = _completed[chunk_index]
            relations = [BiologicalRelation(**r) for r in cached.get("relations", [])]
            return i, ExtractionResult(
                relations=relations,
                rejected=cached.get("rejected", False),
                rejection_reason=cached.get("rejection_reason"),
            )

        result = extract(chunk)

        try:
            entry = {
                "chunk_index": chunk_index,
                "result": {
                    "relations":        [r.model_dump() for r in result.relations],
                    "rejected":         result.rejected,
                    "rejection_reason": result.rejection_reason,
                }
            }
            with _file_lock:
                with open(_progress_path, "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps(entry) + "\n")
        except Exception:
            pass

        return i, result

    indexed_results = []
    with _cf.ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for i, result in pool.map(_process_one, enumerate(chunks)):
            indexed_results.append((i, result))

    indexed_results.sort(key=lambda x: x[0])
    results = [r for _, r in indexed_results]

    try:
        _progress_path.unlink(missing_ok=True)
    except Exception:
        pass

    return results
