"""Layer 8 — verifies generated CSV/MeTTa output against the original paper text."""
import csv
import re
from pathlib import Path


_DELIMITER = "|"


def _sentences(text: str) -> list:
    """Split text into sentences on . ! ? followed by a space or end."""
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]


def _find_supporting_sentence(
    source_text: str,
    subject_name: str,
    object_name: str,
) -> str:
    """
    Find the sentence that most likely supports the extracted relation.
    Returns the sentence containing both subject and object, or the
    sentence containing just the subject if no joint sentence is found.
    """
    if not source_text:
        return ""

    s_lower = subject_name.lower()
    o_lower = object_name.lower()
    text_l  = source_text.lower()
    sents   = _sentences(source_text)

    # Best: sentence contains BOTH
    for sent in sents:
        sl = sent.lower()
        if s_lower in sl and o_lower in sl:
            return sent

    # Fallback: sentence contains subject
    for sent in sents:
        if s_lower in sent.lower():
            return sent

    return ""


def verify_record(record: dict, text_by_doc: dict) -> dict:
    """Verify one relation against its source text; adds verified, supporting_text, mismatch_reason."""
    # Records from CSV: use source_name/target_name (human-readable)
    # Records from Layer 7: use subject_name/object_name
    doc_id       = record.get("source_paper", "") or record.get("document_id", "")
    subject_name = (record.get("source_name", "") or record.get("subject_name", "")
                    or record.get("source_id", ""))
    object_name  = (record.get("target_name", "") or record.get("object_name",  "")
                    or record.get("target_id", ""))
    relation     = record.get("relation",     "")

    # Try to get source text
    source_text = text_by_doc.get(doc_id, "")

    if not source_text:
        return {
            **record,
            "verified":        False,
            "supporting_text": "",
            "mismatch_reason": f"Source text for '{doc_id}' not available for verification",
        }

    text_lower = source_text.lower()
    s_present  = subject_name.lower() in text_lower
    o_present  = object_name.lower()  in text_lower

    if not s_present and not o_present:
        return {
            **record,
            "verified":        False,
            "supporting_text": "",
            "mismatch_reason": f"Neither '{subject_name}' nor '{object_name}' found in source text",
        }
    if not s_present:
        return {
            **record,
            "verified":        False,
            "supporting_text": "",
            "mismatch_reason": f"Subject '{subject_name}' not found in source text",
        }
    if not o_present:
        return {
            **record,
            "verified":        False,
            "supporting_text": "",
            "mismatch_reason": f"Object '{object_name}' not found in source text",
        }

    supporting = _find_supporting_sentence(source_text, subject_name, object_name)
    return {
        **record,
        "verified":        True,
        "supporting_text": supporting,
        "mismatch_reason": "",
    }


def verify_run(run_dir: Path, text_by_doc: dict) -> dict:
    """Read all edge CSVs from run_dir and verify each relation against source text."""
    neo4j_dir = run_dir / "neo4j"
    if not neo4j_dir.exists():
        return {"total": 0, "verified": 0, "mismatched": 0, "results": []}

    all_results = []

    for csv_path in neo4j_dir.rglob("edges_*.csv"):
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=_DELIMITER)
            for row in reader:
                verified = verify_record(dict(row), text_by_doc)
                verified["_source_file"] = csv_path.name
                all_results.append(verified)

    n_verified   = sum(1 for r in all_results if r.get("verified"))
    n_mismatched = sum(1 for r in all_results if not r.get("verified"))

    return {
        "total":      len(all_results),
        "verified":   n_verified,
        "mismatched": n_mismatched,
        "results":    all_results,
    }
