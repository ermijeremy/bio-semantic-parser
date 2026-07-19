"""Layer 8 — Validation Gate: routes records to auto-insert or human review."""


def _is_hard_unresolved(entity_id: str | None) -> bool:
    """True for completely empty/placeholder IDs (NEEDS_REVIEW, empty, None)."""
    return entity_id in ("NEEDS_REVIEW", "", None)


def _is_text_label(entity_id: str) -> bool:
    """True for TEXT: slug IDs — extracted text without ontology mapping."""
    return isinstance(entity_id, str) and entity_id.startswith("TEXT:")


def route(records: list) -> tuple:
    """Split records into (auto_insert, human_review)."""
    auto_insert  = []
    human_review = []

    for r in records:
        verdict    = r.get("validation_verdict", "SKIPPED")
        contra     = r.get("is_contradiction",   False)
        subject_id = r.get("subject_id", "")
        object_id  = r.get("object_id",  "")

        hard_unresolved = (
            _is_hard_unresolved(subject_id) or
            _is_hard_unresolved(object_id)
        )
        text_label = (
            _is_text_label(subject_id) or
            _is_text_label(object_id)
        )

        passes = (
            verdict == "VALID"
            and not contra
            and not hard_unresolved
            and not text_label   # TEXT: entities need canonical ID correction first
        )

        if passes:
            auto_insert.append({**r, "insert_path": "auto"})
        else:
            reason_parts = []
            if text_label and verdict == "VALID":
                if _is_text_label(subject_id):
                    reason_parts.append(
                        f"Subject '{r.get('subject_name','')}' has no canonical ontology ID"
                    )
                if _is_text_label(object_id):
                    reason_parts.append(
                        f"Object '{r.get('object_name','')}' has no canonical ontology ID"
                    )
                reason_parts.append(
                    "provide a canonical ID (e.g. hgnc:1234, mesh:D000001) then approve"
                )
            elif verdict == "REJECT":
                reason_parts.append("semantic validation REJECTED")
            elif verdict == "REVIEW":
                reason_parts.append("semantic validation needs REVIEW")
            elif verdict == "SKIPPED":
                reason_parts.append("semantic validation was skipped — needs manual check")
            else:
                reason_parts.append(f"semantic validation verdict={verdict}")
            if contra:
                reason_parts.append("contradiction detected")
            if hard_unresolved:
                reason_parts.append(
                    f"unresolved entity IDs: "
                    f"subject={subject_id!r} object={object_id!r}"
                )
            existing_reason = r.get("review_reason", "")
            if existing_reason and existing_reason not in " | ".join(reason_parts):
                reason_parts.append(existing_reason[:80])

            human_review.append({
                **r,
                "insert_path": "human_review",
                "gate_reason": " | ".join(reason_parts),
            })

    return auto_insert, human_review
