"""Layer 7 step 5 — second LLM pass to resolve entities that failed normalization."""
import json
import re
from collections import defaultdict
from src.llm_client import make_client, MODEL as _MODEL, TEMPERATURE as _TEMPERATURE


def _client():
    return make_client()


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw)
    return json.loads(raw.strip())


def _resolve_entities_for_paper(
    unresolved_names: list,
    unresolved_types: list,
    already_resolved: list,
    paper_text: str,
) -> dict:
    """
    Second LLM call: infer canonical IDs for unresolved entities using
    paper context and already-resolved entities from the same paper.

    Returns: {entity_name: "canonical_id"} or STILL_UNKNOWN if not resolvable.
    """
    resolved_context = "\n".join(
        f"  {e['name']} ({e['type']}) → {e['id']}"
        for e in already_resolved[:20]
    )
    unresolved_list = "\n".join(
        f"  - {name} (type: {etype})"
        for name, etype in zip(unresolved_names, unresolved_types)
    )

    prompt = (
        f"PAPER TEXT EXCERPT:\n\"{paper_text[:2000]}\"\n\n"
        f"ALREADY RESOLVED ENTITIES IN THIS PAPER:\n"
        f"{resolved_context if resolved_context else '  (none yet)'}\n\n"
        f"UNRESOLVED ENTITIES THAT NEED CANONICAL IDs:\n{unresolved_list}\n\n"
        "For each unresolved entity, provide the most likely canonical identifier.\n"
        "Use these formats: MESH:D…  NCBI_GENE:…  CHEBI:…  UNIPROT:…\n"
        "If you cannot determine it confidently, return STILL_UNKNOWN.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "<entity_name>": "<canonical_id or STILL_UNKNOWN>",\n'
        "  ...\n"
        "}"
    )

    try:
        response = _client().chat.completions.create(
            model           = _MODEL,
            messages        = [
                {"role": "system", "content":
                 "You are a biomedical entity normalisation expert. "
                 "Return only valid JSON with canonical identifiers. "
                 "Never guess — return STILL_UNKNOWN if not certain."},
                {"role": "user", "content": prompt},
            ],
            temperature     = _TEMPERATURE,
            response_format = {"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        return _parse_json(raw)
    except Exception:
        return {name: "STILL_UNKNOWN" for name in unresolved_names}


def resolve(records: list, text_by_doc: dict) -> list:
    """Attempt second-pass resolution for records with NEEDS_REVIEW entity IDs."""
    has_unresolved = any(
        r.get("subject_id") == "NEEDS_REVIEW" or r.get("object_id") == "NEEDS_REVIEW"
        for r in records
    )
    if not has_unresolved:
        return records

    # Group incomplete records by document
    by_doc: dict = defaultdict(list)
    for r in records:
        if r.get("subject_id") == "NEEDS_REVIEW" or r.get("object_id") == "NEEDS_REVIEW":
            by_doc[r.get("document_id", "")].append(r)

    # Build resolution map per document
    resolution_map: dict = {}

    for doc_id, doc_records in by_doc.items():
        unresolved_names: list = []
        unresolved_types: list = []
        already_resolved: list = []
        seen_unresolved: set   = set()
        # Collect chunk texts from the specific records that have unresolved entities.
        # This gives the LLM the sentence where the entity actually appeared rather
        # than an arbitrary first-2000-chars slice of the full paper.
        chunk_texts: list = []

        for r in doc_records:   
            chunk_text = r.get("_chunk_text", "")
            if chunk_text and chunk_text not in chunk_texts:
                chunk_texts.append(chunk_text)
            for name_key, type_key, id_key in [
                ("subject_name", "subject_type", "subject_id"),
                ("object_name",  "object_type",  "object_id"),
            ]:
                name = r.get(name_key, "")
                eid  = r.get(id_key,  "")
                if eid == "NEEDS_REVIEW" and name and name not in seen_unresolved:
                    unresolved_names.append(name)
                    unresolved_types.append(r.get(type_key, "OTHER"))
                    seen_unresolved.add(name)
                elif eid and eid not in ("NEEDS_REVIEW", ""):
                    already_resolved.append({
                        "name": name, "type": r.get(type_key, ""), "id": eid
                    })

        # Use the chunks where unresolved entities appeared; fall back to doc text.
        paper_text = " ".join(chunk_texts) if chunk_texts else text_by_doc.get(doc_id, "")

        if unresolved_names:
            resolved = _resolve_entities_for_paper(
                unresolved_names, unresolved_types, already_resolved, paper_text
            )
            for name, cid in resolved.items():
                resolution_map[name] = cid

    # Apply resolutions to all records
    updated = []
    for r in records:
        rec = dict(r)
        for name_key, id_key, needs_key in [
            ("subject_name", "subject_id", "subject_needs_review"),
            ("object_name",  "object_id",  "object_needs_review"),
        ]:
            name = rec.get(name_key, "")
            if rec.get(id_key) == "NEEDS_REVIEW" and name in resolution_map:
                resolved_id = resolution_map[name]
                if resolved_id != "STILL_UNKNOWN":
                    rec[id_key]   = resolved_id
                    rec[needs_key]= False

        # Re-evaluate review flag
        still_needs_review = (
            rec.get("subject_id") == "NEEDS_REVIEW" or
            rec.get("object_id")  == "NEEDS_REVIEW"
        )
        if still_needs_review:
            rec["flagged_for_review"] = True
            reason = rec.get("review_reason", "")
            rec["review_reason"] = (reason + " | UNRESOLVED after two-pass").strip(" |")

        updated.append(rec)

    return updated
