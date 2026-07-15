"""Layer 8 — writes validated records to Neo4j CSV and MeTTa."""
from pathlib import Path
from src.publish import neo4j_writer, metta_writer


def insert_to_atomspace(records: list, run_dir: Path, formats: str = "both") -> dict:
    """Write records to Neo4j CSV and/or MeTTa (formats: 'neo4j', 'metta', 'both')."""
    if not records:
        return {"records": 0, "neo4j": {}, "metta": {}}

    neo4j_summary = (neo4j_writer.write(records, run_dir=run_dir)
                     if formats in ("neo4j", "both") else {})
    metta_summary = (metta_writer.write(records, run_dir=run_dir)
                     if formats in ("metta", "both") else {})

    return {
        "records": len(records),
        "run_dir": str(run_dir),
        "neo4j":   neo4j_summary,
        "metta":   metta_summary,
    }
