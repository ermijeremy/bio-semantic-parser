"""Layer 7 step 3 — flag opposing relations for the same entity pair as contradictions."""
import sqlite3
from pathlib import Path

from src.schema.taxonomy import OPPOSING_RELATIONS, RelationType


_DB_PATH = Path("data/triple_store.db")


def _get_conn() -> sqlite3.Connection:
    import os as _os
    path = Path(_os.getenv("TRIPLE_STORE_PATH", str(_DB_PATH)))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def check_contradiction(record: dict) -> dict:
    """Flag the record if an opposing relation already exists for the same entity pair."""
    try:
        rel_enum = RelationType(record.get("relation", ""))
    except ValueError:
        return record   # unknown relation type — skip

    opposing = OPPOSING_RELATIONS.get(rel_enum)
    if opposing is None:
        return record   # no known opposite for this relation type

    subject_id = record.get("subject_id", "")
    object_id  = record.get("object_id",  "")

    if not subject_id or not object_id:
        return record

    negated = 1 if record.get("negated") else 0

    import os as _os
    db_path = Path(_os.getenv("TRIPLE_STORE_PATH", str(_DB_PATH)))
    if not db_path.exists():
        return record

    conn = _get_conn()
    row  = conn.execute(
        "SELECT id, source_papers FROM triples "
        "WHERE subject_id=? AND relation=? AND object_id=? AND negated=?",
        (subject_id, opposing.value, object_id, negated),
    ).fetchone()
    conn.close()

    if row:
        reason = (
            f"CONTRADICTION: '{record['relation']}' conflicts with existing "
            f"'{opposing.value}' for same entity pair (triple_id={row['id']} "
            f"sources={row['source_papers']})"
        )
        existing_reason = record.get("review_reason", "")
        combined = (existing_reason + " | " + reason).strip(" |")
        return {
            **record,
            "is_contradiction":   True,
            "flagged_for_review": True,
            "review_reason":      combined,
        }

    return record


def flag_existing_as_contradiction(triple_id: int, reason: str) -> None:
    """Mark an already-stored triple as a contradiction (called when new opposing arrives)."""
    import os as _os
    db_path = Path(_os.getenv("TRIPLE_STORE_PATH", str(_DB_PATH)))
    if not db_path.exists():
        return
    conn = _get_conn()
    conn.execute(
        "UPDATE triples SET is_contradiction=1, flagged_for_review=1, "
        "review_reason=COALESCE(review_reason||' | '||?, ?) WHERE id=?",
        (reason, reason, triple_id),
    )
    conn.commit()
    conn.close()
