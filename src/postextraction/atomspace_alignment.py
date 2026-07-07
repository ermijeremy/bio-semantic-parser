"""Layer 7 step 7 — check if entity nodes already exist in the KG before writing."""
import sqlite3
from pathlib import Path

_DB_PATH = Path("data/triple_store.db")


def _active_db() -> Path:
    import os as _os
    return Path(_os.getenv("TRIPLE_STORE_PATH", str(_DB_PATH)))


def _known_entities() -> set:
    """Return all canonical IDs present in the triple store."""
    db = _active_db()
    if not db.exists():
        return set()
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT DISTINCT subject_id FROM triples "
        "UNION "
        "SELECT DISTINCT object_id  FROM triples"
    ).fetchall()
    conn.close()
    return {row[0] for row in rows if row[0] and row[0] != "NEEDS_REVIEW"}


def align(records: list) -> list:
    """
    Check each record's subject_id and object_id against the KG.
    Returns records enriched with alignment metadata.
    """
    known = _known_entities()
    aligned = []

    for r in records:
        subject_id = r.get("subject_id", "")
        object_id  = r.get("object_id",  "")

        s_exists = subject_id in known and subject_id not in ("NEEDS_REVIEW", "")
        o_exists = object_id  in known and object_id  not in ("NEEDS_REVIEW", "")

        if s_exists and o_exists:
            action = "connect_existing"
        elif s_exists or o_exists:
            action = "create_one_new"
        else:
            action = "both_new"

        aligned.append({
            **r,
            "subject_node_exists": s_exists,
            "object_node_exists":  o_exists,
            "alignment_action":    action,
        })

    return aligned
