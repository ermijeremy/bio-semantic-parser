"""Layer 8 — Validation Gate: routes records to auto-insert or human review."""


def _is_hard_unresolved(entity_id: str) -> bool:
    """True only for completely unresolved IDs — TEXT: slugs are acceptable."""
    return entity_id in ("NEEDS_REVIEW", "", None)


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

        passes = (
            verdict == "VALID"
            and not contra
            and not hard_unresolved
        )

        if passes:
            auto_insert.append({**r, "insert_path": "auto"})
        else:
            reason_parts = []
            if verdict == "REJECT":
                reason_parts.append("semantic validation REJECTED")
            elif verdict == "REVIEW":
                reason_parts.append("semantic validation needs REVIEW")
            elif verdict == "SKIPPED":
                reason_parts.append("semantic validation was skipped — needs manual check")
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
