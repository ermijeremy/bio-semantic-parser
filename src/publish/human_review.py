"""Layer 8 — Human Review Queue: stores flagged records for domain expert review."""
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path


_QUEUE_PATH = Path(os.getenv("HUMAN_REVIEW_QUEUE", "data/human_review.jsonl"))
_CSV_PATH   = _QUEUE_PATH.with_suffix(".csv")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(records: list, run_dir: Path = None, target_format: str = "both") -> int:
    """Append flagged records to the human review queue. Returns number written."""
    if not records:
        return 0

    # Use run-specific path if provided, else fall back to global path
    queue_path = (run_dir / "human_review.jsonl") if run_dir else _QUEUE_PATH
    csv_path   = queue_path.with_suffix(".csv")
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with open(queue_path, "a", encoding="utf-8") as jf:
        for r in records:
            entry = {
                "timestamp":          _now(),
                "status":             "PENDING",      # PENDING / APPROVED / REJECTED / EDITED
                "target_format":      target_format,  # neo4j | metta | both — which DB to commit to on approval
                "document_id":        r.get("document_id", ""),
                "source_name":        r.get("source_name", ""),
                "section":            r.get("section", ""),
                # The extraction
                "subject_name":       r.get("subject_name", ""),
                "subject_type":       r.get("subject_type", ""),
                "subject_id":         r.get("subject_id",   ""),
                "relation":           r.get("relation",     ""),
                "object_name":        r.get("object_name",  ""),
                "object_type":        r.get("object_type",  ""),
                "object_id":          r.get("object_id",    ""),
                "negated":            r.get("negated",      False),
                # Quality metadata
                "confidence":         r.get("confidence",   0.0),
                "validation_verdict": r.get("validation_verdict", ""),
                "is_contradiction":   r.get("is_contradiction", False),
                "gate_reason":        r.get("gate_reason",  ""),
                "review_reason":      r.get("review_reason",""),
                # Audit trail
                "reasoning":          r.get("reasoning",    ""),
                "suggested_correction": r.get("suggested_correction", ""),
                # Biological context
                "species":            r.get("species",      ""),
                "tissue":             r.get("tissue",       ""),
                "condition":          r.get("condition",    ""),
                "effect_size":        r.get("effect_size",  ""),
                # Actions for reviewer
                "reviewer_action":    "",    # filled by reviewer
                "reviewer_note":      "",
                "reviewed_at":        "",
            }
            jf.write(json.dumps(entry) + "\n")
            count += 1

    _write_csv([{**r, "target_format": target_format} for r in records], csv_path)
    return count


def _write_csv(records: list, csv_path: Path = None) -> None:
    """Write / append a human-readable CSV version of the review queue."""
    if csv_path is None:
        csv_path = _CSV_PATH
    fields = [
        "timestamp", "status", "target_format", "document_id", "section",
        "subject_name", "subject_id", "relation",
        "object_name", "object_id", "negated",
        "confidence", "validation_verdict", "is_contradiction",
        "gate_reason", "reasoning",
        "species", "tissue", "condition", "effect_size",
        "reviewer_action", "reviewer_note", "reviewed_at",
    ]
    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as cf:
        writer = csv.DictWriter(cf, fieldnames=fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        ts = _now()
        for r in records:
            writer.writerow({
                "timestamp":          ts,
                "status":             "PENDING",
                "target_format":      r.get("target_format", "both"),
                "document_id":        r.get("document_id", ""),
                "section":            r.get("section", ""),
                "subject_name":       r.get("subject_name", ""),
                "subject_id":         r.get("subject_id",   ""),
                "relation":           r.get("relation",     ""),
                "object_name":        r.get("object_name",  ""),
                "object_id":          r.get("object_id",    ""),
                "negated":            r.get("negated",      False),
                "confidence":         r.get("confidence",   0.0),
                "validation_verdict": r.get("validation_verdict", ""),
                "is_contradiction":   r.get("is_contradiction", False),
                "gate_reason":        r.get("gate_reason",  ""),
                "reasoning":          (r.get("reasoning", "") or "")[:300],
                "species":            r.get("species",      ""),
                "tissue":             r.get("tissue",       ""),
                "condition":          r.get("condition",    ""),
                "effect_size":        r.get("effect_size",  ""),
                "reviewer_action":    "",
                "reviewer_note":      "",
                "reviewed_at":        "",
            })


def load_pending(queue_path: Path = None) -> list:
    """Return all records with status=PENDING from the queue."""
    path = queue_path or _QUEUE_PATH
    if not path.exists():
        return []
    pending = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("status") == "PENDING":
                    pending.append(entry)
            except json.JSONDecodeError:
                pass
    return pending


def count_pending(queue_path: Path = None) -> int:
    return len(load_pending(queue_path))


def approve_records(approved: list, staging_db: str, queue_path: Path = None) -> int:
    """Commit approved records into the staging DB and mark them APPROVED in the JSONL."""
    import sqlite3 as _sq
    if not approved or not staging_db:
        return 0

    queue_path = queue_path or _QUEUE_PATH
    conn = _sq.connect(staging_db)
    conn.row_factory = _sq.Row

    # Ensure schema matches staging DB
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triples (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id       TEXT NOT NULL,
            subject_name     TEXT NOT NULL,
            subject_type     TEXT NOT NULL DEFAULT '',
            relation         TEXT NOT NULL,
            object_id        TEXT NOT NULL,
            object_name      TEXT NOT NULL,
            object_type      TEXT NOT NULL DEFAULT '',
            negated          INTEGER NOT NULL DEFAULT 0,
            confidence       REAL NOT NULL DEFAULT 0.0,
            source_papers    TEXT NOT NULL DEFAULT '[]',
            reasoning        TEXT NOT NULL DEFAULT '',
            section          TEXT NOT NULL DEFAULT '',
            species          TEXT NOT NULL DEFAULT '',
            tissue           TEXT NOT NULL DEFAULT '',
            condition        TEXT NOT NULL DEFAULT '',
            effect_size      TEXT NOT NULL DEFAULT '',
            flagged_for_review INTEGER NOT NULL DEFAULT 0,
            validation_verdict TEXT NOT NULL DEFAULT '',
            created_at         TEXT NOT NULL DEFAULT '',
            updated_at         TEXT NOT NULL DEFAULT '',
            UNIQUE(subject_id, relation, object_id, negated)
        )
    """)

    count = 0
    now = _now()
    for r in approved:
        try:
            # Remove old flagged triple — relation may have been corrected by reviewer
            conn.execute(
                "DELETE FROM triples WHERE subject_name=? AND relation=? AND object_name=? AND flagged_for_review=1",
                (r.get("subject_name",""), r.get("relation",""), r.get("object_name",""))
            )
            conn.execute("""
                INSERT OR REPLACE INTO triples
                (subject_id, subject_name, subject_type, relation,
                 object_id, object_name, object_type, negated,
                 confidence, source_papers, reasoning,
                 species, tissue, condition, effect_size,
                 flagged_for_review, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)
            """, (
                r.get("subject_id")  or f"TEXT:{r.get('subject_name','')}",
                r.get("subject_name",""),
                r.get("subject_type",""),
                r.get("relation",""),
                r.get("object_id")   or f"TEXT:{r.get('object_name','')}",
                r.get("object_name",""),
                r.get("object_type",""),
                1 if r.get("negated") else 0,
                r.get("confidence", 0.0),
                json.dumps([r.get("document_id","")]),
                r.get("reasoning",""),
                r.get("species",""),
                r.get("tissue",""),
                r.get("condition",""),
                r.get("effect_size",""),
                now,
                now,
            ))
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()

    # Update status in JSONL
    if queue_path.exists():
        approved_keys = {
            (r.get("subject_name",""), r.get("relation",""), r.get("object_name",""))
            for r in approved
        }
        lines = []
        for line in queue_path.read_text().splitlines():
            entry = None
            try:
                entry = json.loads(line)
                key = (entry.get("subject_name",""), entry.get("relation",""), entry.get("object_name",""))
                if key in approved_keys:
                    entry["status"]          = "APPROVED"
                    entry["reviewed_at"]     = now
                    entry["reviewer_action"] = "approve"
            except Exception:
                pass
            lines.append(json.dumps(entry) if isinstance(entry, dict) else line)
        queue_path.write_text("\n".join(lines) + "\n")

    return count
