"""Layer 7 step 6 — LLM semantic validator: verifies each extraction across five dimensions."""
import os
from dotenv import load_dotenv

from src.schema.taxonomy import TAXONOMY, RelationType
from src.llm_client import call_llm as _call_llm, parse_json as _parse_json_client

load_dotenv()

_MODEL       = os.getenv("LLM_MODEL",       "gemma4")
_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))

def _is_skipped() -> bool:
    return os.getenv("SKIP_SEMANTIC_VALIDATION", "false").lower() == "true"


def _parse_json(raw: str) -> dict:
    return _parse_json_client(raw)


def _taxonomy_definition(relation: str) -> str:
    """Return definition + not_this for the given relation type."""
    try:
        rel_enum = RelationType(relation)
        entry    = TAXONOMY.get(rel_enum, {})
        return (
            f"Definition : {entry.get('definition', 'N/A')}\n"
            f"Example    : {entry.get('example', 'N/A')}\n"
            f"NOT this   : {entry.get('not_this', 'N/A')}"
        )
    except ValueError:
        return f"(unknown relation type: {relation})"


def _build_validator_prompt(record: dict, source_text: str) -> list:
    subject  = record.get("subject_name", "")
    relation = record.get("relation", "")
    obj      = record.get("object_name", "")
    negated  = record.get("negated", False)
    section  = record.get("section", "unknown")
    reasoning_from_layer6 = record.get("reasoning", "")

    taxonomy_def = _taxonomy_definition(relation)

    system = (
        "You are a strict independent peer reviewer for biomedical relation extraction.\n"
        "You will evaluate whether an extracted relation is correct by checking it against "
        "the original source text.\n"
        "You must be rigorous — do not give the benefit of the doubt.\n"
        "You must return ONLY valid JSON, no additional text."
    )

    user = f"""ORIGINAL SOURCE TEXT (section: {section}):
\"{source_text}\"

EXTRACTED RELATION TO VERIFY:
  Subject  : {subject}
  Relation : {relation}{'  [NEGATED]' if negated else ''}
  Object   : {obj}

TAXONOMY DEFINITION FOR '{relation}':
{taxonomy_def}

LAYER 6 REASONING (what the extraction LLM said):
{reasoning_from_layer6}

TASK: Verify this extraction across 5 dimensions. For each, answer true/false and explain.

Return ONLY this JSON:
{{
  "subject_correct": true | false,
  "subject_issue": "<empty string if correct, or describe the problem>",

  "object_correct": true | false,
  "object_issue": "<empty string if correct, or describe the problem>",

  "relation_correct": true | false,
  "relation_issue": "<empty string if correct — e.g. 'text says upregulates not activates', or 'direction is reversed'>",

  "negation_correct": true | false,
  "negation_issue": "<empty string if correct, or describe the problem>",

  "support_strong": true | false,
  "support_issue": "<empty string if strong support — e.g. 'this is a background claim in Introduction, not a result'>",

  "verdict": "VALID" | "REVIEW" | "REJECT",
  "verdict_reasoning": "<1-3 sentences explaining the overall verdict>",
  "suggested_correction": "<if REJECT or REVIEW: what the correct extraction should be, else empty string>"
}}

VERDICT RULES:
  VALID  — all 5 dimensions correct
  REVIEW — 1-2 issues, extraction is plausible but needs human confirmation
  REJECT — 3+ issues, or wrong direction, or hallucinated entity, or complete mismatch
"""

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]


def validate(record: dict, source_text: str) -> dict:
    """Run semantic validation for one extracted relation; never raises."""
    # ── Skip conditions ───────────────────────────────────────────
    if _is_skipped():
        return {**record,
                "validation_verdict":  "SKIPPED",
                "validation_reasoning": "SKIP_SEMANTIC_VALIDATION=true"}

    if record.get("is_contradiction"):
        return {**record,
                "validation_verdict":  "SKIPPED",
                "validation_reasoning": "already contradiction-flagged — goes to human review"}

    # ── Call validator LLM ────────────────────────────────────────
    messages = _build_validator_prompt(record, source_text)

    try:
        raw  = _call_llm(messages=messages, model=_MODEL, temperature=_TEMPERATURE)
        data = _parse_json(raw)
    except Exception as exc:
        return {**record,
                "validation_verdict":  "SKIPPED",
                "validation_reasoning": f"LLM call failed: {exc}"}

    # ── Parse verdict ──────────────────────────────────────────────
    verdict   = data.get("verdict", "REVIEW")
    reasoning = data.get("verdict_reasoning", "")
    correction= data.get("suggested_correction", "")

    issues = []
    for dim, issue_key in [
        ("subject",  "subject_issue"),
        ("object",   "object_issue"),
        ("relation", "relation_issue"),
        ("negation", "negation_issue"),
        ("support",  "support_issue"),
    ]:
        correct_key = f"{dim}_correct" if dim != "support" else "support_strong"
        if not data.get(correct_key, True):
            issue_text = data.get(issue_key, "")
            if issue_text:
                issues.append(f"{dim.upper()}: {issue_text}")

    # ── Update record ─────────────────────────────────────────────
    flagged       = record.get("flagged_for_review", False)
    review_reason = record.get("review_reason", "")

    if verdict in ("REVIEW", "REJECT"):
        flagged = True
        new_reason = f"SEMANTIC_{verdict}: {reasoning}"
        if issues:
            new_reason += " | Issues: " + "; ".join(issues)
        if correction:
            new_reason += f" | Suggested: {correction}"
        review_reason = (review_reason + " | " + new_reason).strip(" |")

    return {
        **record,
        # Five dimension results
        "val_subject_correct":    data.get("subject_correct",  True),
        "val_object_correct":     data.get("object_correct",   True),
        "val_relation_correct":   data.get("relation_correct", True),
        "val_negation_correct":   data.get("negation_correct", True),
        "val_support_strong":     data.get("support_strong",   True),
        # Overall verdict
        "validation_verdict":     verdict,
        "validation_reasoning":   reasoning,
        "suggested_correction":   correction,
        "validation_issues":      issues,
        # Propagate to review flags
        "flagged_for_review":     flagged,
        "review_reason":          review_reason,
        "is_semantically_valid":  (verdict == "VALID"),
    }


# ── Batch validation (optimized) ──────────────────────────────────────────────

_BATCH_SIZE   = int(os.getenv("SEMANTIC_VALIDATION_BATCH",   "4"))
_BATCH_WORKERS= int(os.getenv("SEMANTIC_VALIDATION_WORKERS", "1"))


def _build_batch_prompt(items: list) -> list:
    """Build a single LLM prompt that validates N relations at once."""
    # All items must share the same source_text (grouped by chunk); sent once — no truncation
    shared_source = items[0][1] if items else ""

    blocks = []
    for idx, (record, _) in enumerate(items, 1):
        subject  = record.get("subject_name", "")
        relation = record.get("relation", "")
        obj      = record.get("object_name", "")
        negated  = record.get("negated", False)
        reasoning= (record.get("reasoning", "") or "")[:200]
        blocks.append(
            f"--- RELATION {idx} ---\n"
            f"Subject : {subject}\n"
            f"Relation: {relation}{'  [NEGATED]' if negated else ''}\n"
            f"Object  : {obj}\n"
            f"Reasoning from extraction LLM: {reasoning}"
        )

    user = (
        "SOURCE TEXT (all relations below were extracted from this same chunk of text):\n"
        f"\"{shared_source}\"\n\n"
        "Validate each of the following relations against the SOURCE TEXT above.\n"
        "For each relation return one JSON object in a top-level 'results' array.\n\n"
        + "\n\n".join(blocks)
        + "\n\nReturn ONLY this JSON:\n"
        "{\n  \"results\": [\n"
        "    {\n"
        "      \"index\": 1,\n"
        "      \"subject_correct\": true|false, \"subject_issue\": \"\",\n"
        "      \"object_correct\": true|false, \"object_issue\": \"\",\n"
        "      \"relation_correct\": true|false, \"relation_issue\": \"\",\n"
        "      \"negation_correct\": true|false, \"negation_issue\": \"\",\n"
        "      \"support_strong\": true|false, \"support_issue\": \"\",\n"
        "      \"verdict\": \"VALID\"|\"REVIEW\"|\"REJECT\",\n"
        "      \"verdict_reasoning\": \"...\",\n"
        "      \"suggested_correction\": \"\"\n"
        "    }\n  ]\n}"
    )
    return [
        {"role": "system", "content":
         "You are a strict biomedical fact-checker. Validate each relation. "
         "Return only valid JSON with a 'results' array."},
        {"role": "user", "content": user},
    ]


def _apply_verdict(record: dict, data: dict) -> dict:
    """Apply one verdict dict (from batch or single) to a record."""
    verdict   = data.get("verdict", "REVIEW")
    reasoning = data.get("verdict_reasoning", "")
    correction= data.get("suggested_correction", "")

    issues = []
    for dim, issue_key in [
        ("subject",  "subject_issue"),
        ("object",   "object_issue"),
        ("relation", "relation_issue"),
        ("negation", "negation_issue"),
        ("support",  "support_issue"),
    ]:
        correct_key = f"{dim}_correct" if dim != "support" else "support_strong"
        if not data.get(correct_key, True):
            issue_text = data.get(issue_key, "")
            if issue_text:
                issues.append(f"{dim.upper()}: {issue_text}")

    flagged       = record.get("flagged_for_review", False)
    review_reason = record.get("review_reason", "")
    if verdict in ("REVIEW", "REJECT"):
        flagged = True
        new_reason = f"SEMANTIC_{verdict}: {reasoning}"
        if issues:
            new_reason += " | Issues: " + "; ".join(issues)
        if correction:
            new_reason += f" | Suggested: {correction}"
        review_reason = (review_reason + " | " + new_reason).strip(" |")

    return {
        **record,
        "val_subject_correct":    data.get("subject_correct",  True),
        "val_object_correct":     data.get("object_correct",   True),
        "val_relation_correct":   data.get("relation_correct", True),
        "val_negation_correct":   data.get("negation_correct", True),
        "val_support_strong":     data.get("support_strong",   True),
        "validation_verdict":     verdict,
        "validation_reasoning":   reasoning,
        "suggested_correction":   correction,
        "validation_issues":      issues,
        "flagged_for_review":     flagged,
        "review_reason":          review_reason,
        "is_semantically_valid":  (verdict == "VALID"),
    }


def validate_batch(pairs: list) -> list:
    """Validate a batch of (record, source_text) pairs in one LLM call; falls back to SKIPPED on error."""
    if not pairs:
        return []

    messages = _build_batch_prompt(pairs)
    try:
        raw  = _call_llm(messages=messages, model=_MODEL, temperature=_TEMPERATURE,
                         max_tokens=int(os.getenv("LLM_OUTPUT_TOKENS", "4096")))
        data = _parse_json(raw)
        results = data.get("results", [])
    except Exception as exc:
        # Whole batch failed — return all as SKIPPED
        return [
            {**record, "validation_verdict": "SKIPPED",
             "validation_reasoning": f"Batch validation failed: {exc}"}
            for record, _ in pairs
        ]

    # Map results back to records by index
    results_by_idx = {r.get("index", i+1): r for i, r in enumerate(results)}
    updated = []
    for i, (record, _) in enumerate(pairs, 1):
        verdict_data = results_by_idx.get(i, {})
        if not verdict_data:
            updated.append({**record, "validation_verdict": "SKIPPED",
                            "validation_reasoning": "No result returned for this relation"})
        else:
            updated.append(_apply_verdict(record, verdict_data))
    return updated
