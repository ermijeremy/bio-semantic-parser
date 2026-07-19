#!/usr/bin/env python3
"""
tools/validate_output.py
─────────────────────────
Post-processing audit script for the bio-semantic-parser output.

Reads every generated CSV and MeTTa file from data/kg_output/ and runs
six independent checks to verify the output is correct and complete.

Six checks
──────────
  1. Relation types     — every relation in edge files is in the RelationType taxonomy
  2. Entity ID format   — canonical IDs follow standard patterns (MESH, NCBI, etc.)
  3. Orphan edges       — every node referenced by an edge exists in a node file
  4. MeTTa syntax       — every triple follows the (relation (type ID) (type ID)) format
  5. Duplicate rows     — no duplicate (source_id, target_id, relation) in edge CSVs
  6. Coverage report    — counts of nodes, edges, auto vs review, types breakdown

Exit codes:
  0 — all checks passed (warnings allowed)
  1 — one or more FAIL checks

Run from the project root:
  python tools/validate_output.py
  python tools/validate_output.py --neo4j-dir data/kg_output/neo4j
  python tools/validate_output.py --metta-dir data/kg_output/metta
  python tools/validate_output.py --output tools/validation_report.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.schema.taxonomy import RelationType  # noqa: E402

# ── Known canonical ID patterns ────────────────────────────────────────────────
# PASS: recognised standard ID → will resolve to a node in standard databases
# WARN: fuzzy slug (TEXT:…) → human review needed but structurally valid
# FAIL: NEEDS_REVIEW or empty → should never reach the output files

_STANDARD_PATTERNS = [
    re.compile(r"^MESH:[A-Z][0-9]{6,}"),        # MeSH  e.g. MESH:D020123
    re.compile(r"^NCBI_GENE:[0-9]+$"),           # NCBI Gene (with prefix)
    re.compile(r"^[0-9]+$"),                     # NCBI Gene (bare integer)
    re.compile(r"^CHEBI:[0-9]+$"),               # ChEBI
    re.compile(r"^UNIPROT:[A-Z0-9]+$"),          # UniProt
    re.compile(r"^GO:[0-9]{7}$"),                # Gene Ontology
    re.compile(r"^HP:[0-9]{7}$"),                # HPO
    re.compile(r"^DOID:[0-9]+$"),                # Disease Ontology
    re.compile(r"^NCBITaxon:[0-9]+$"),           # NCBI Taxonomy
    re.compile(r"^[0-9]+$"),                     # Bare integer (NCBI Gene / Taxon)
]

_FUZZY_PATTERN    = re.compile(r"^TEXT:.+$")
_INVALID_PATTERNS = {"NEEDS_REVIEW", "", None}

_VALID_RELATIONS  = {r.value for r in RelationType}

# ── ANSI colours ───────────────────────────────────────────────────────────────
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"


def _pass(msg: str)  -> str: return f"{_GREEN}✓ PASS{_RESET}  {msg}"
def _warn(msg: str)  -> str: return f"{_YELLOW}⚠ WARN{_RESET}  {msg}"
def _fail(msg: str)  -> str: return f"{_RED}✗ FAIL{_RESET}  {msg}"
def _info(msg: str)  -> str: return f"  ℹ  {msg}"
def _head(msg: str)  -> str: return f"\n{_BOLD}{msg}{_RESET}"


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _classify_id(cid: str) -> str:
    """Return 'standard' | 'fuzzy' | 'invalid'."""
    if cid in _INVALID_PATTERNS:
        return "invalid"
    if _FUZZY_PATTERN.match(cid):
        return "fuzzy"
    for pat in _STANDARD_PATTERNS:
        if pat.match(cid):
            return "standard"
    return "fuzzy"   # unknown format but non-empty → treat as fuzzy


def _read_csv(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="|"))


def _metta_triples(path: Path) -> list:
    """Extract all (relation, source_type, source_id, target_type, target_id) from a .metta edge file."""
    triples = []
    pattern = re.compile(
        r'^\((\S+)\s+\((\S+)\s+(\S+)\)\s+\((\S+)\s+(\S+)\)\)'
    )
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        m = pattern.match(line)
        if m:
            triples.append({
                "relation":    m.group(1),
                "source_type": m.group(2),
                "source_id":   m.group(3),
                "target_type": m.group(4),
                "target_id":   m.group(5),
            })
    return triples


# ══════════════════════════════════════════════════════════════════════════════
# Check 1 — Relation types
# ══════════════════════════════════════════════════════════════════════════════

def _rel_from_filename(stem: str) -> str:
    """
    Extract the relation type from an edge filename like
    edges_small_molecule_inhibits_protein.
    Source and target types can contain underscores, so we match by
    scanning for a known relation value in the stem.
    Longest match first to avoid partial-match errors.
    """
    body = re.sub(r"^edges_", "", stem)
    # Try each valid relation, longest first to avoid 'regulates' matching inside 'positively_regulates'
    for rel in sorted(_VALID_RELATIONS, key=len, reverse=True):
        if f"_{rel}_" in f"_{body}_":
            return rel
    return body   # fallback — full body if no match


def check_relation_types(neo4j_dir: Path, metta_dir: Path) -> dict:
    """Every relation in edge files must be in the 57-type taxonomy."""
    unknown: dict = defaultdict(list)

    for path in neo4j_dir.rglob("edges_*.csv"):
        rel = _rel_from_filename(path.stem)
        if rel and rel not in _VALID_RELATIONS:
            unknown[rel].append(str(path.name))

    if metta_dir.exists():
        for path in metta_dir.rglob("edges_*.metta"):
            for triple in _metta_triples(path):
                rel = triple["relation"]
                if rel not in _VALID_RELATIONS:
                    unknown[rel].append(str(path.name))

    issues = []
    for rel, files in unknown.items():
        unique_files = list(set(files))
        issues.append(f"  '{rel}' in {unique_files}")

    if issues:
        return {"status": "FAIL", "message": f"{len(unknown)} unknown relation type(s)", "details": issues}
    return {"status": "PASS", "message": "all relation types are in the taxonomy", "details": []}


# ══════════════════════════════════════════════════════════════════════════════
# Check 2 — Entity ID format
# ══════════════════════════════════════════════════════════════════════════════

def check_entity_ids(neo4j_dir: Path) -> dict:
    """Every canonical ID in node CSVs should be a recognised standard format."""
    standard_count = 0
    fuzzy_ids:   list = []
    invalid_ids: list = []

    for path in neo4j_dir.rglob("nodes_*.csv"):
        for row in _read_csv(path):
            cid   = row.get("id", "")
            cname = row.get("name", "")
            cls   = _classify_id(cid)
            if cls == "standard":
                standard_count += 1
            elif cls == "fuzzy":
                fuzzy_ids.append(f"{cid}  ({cname})  [{path.name}]")
            else:
                invalid_ids.append(f"{cid!r}  ({cname})  [{path.name}]")

    details = []
    if invalid_ids:
        details.append("  INVALID IDs (should never appear in output):")
        details.extend(f"    {x}" for x in invalid_ids[:10])
    if fuzzy_ids:
        details.append(f"  Fuzzy IDs (TEXT:… — need domain expert normalisation):")
        details.extend(f"    {x}" for x in fuzzy_ids[:10])

    total = standard_count + len(fuzzy_ids) + len(invalid_ids)
    msg = (
        f"{standard_count}/{total} standard IDs  ·  "
        f"{len(fuzzy_ids)} fuzzy  ·  {len(invalid_ids)} invalid"
    )

    if invalid_ids:
        return {"status": "FAIL", "message": msg, "details": details}
    if fuzzy_ids:
        return {"status": "WARN", "message": msg, "details": details}
    return {"status": "PASS", "message": msg, "details": []}


# ══════════════════════════════════════════════════════════════════════════════
# Check 3 — Orphan edges
# ══════════════════════════════════════════════════════════════════════════════

def check_orphan_edges(neo4j_dir: Path) -> dict:
    """Every source_id and target_id in edge CSVs must exist in a node CSV."""
    known_nodes: set = set()
    for path in neo4j_dir.rglob("nodes_*.csv"):
        for row in _read_csv(path):
            nid = row.get("id", "")
            if nid:
                known_nodes.add(nid)

    orphans: list = []
    for path in neo4j_dir.rglob("edges_*.csv"):
        for row in _read_csv(path):
            for key in ("source_id", "target_id"):
                nid = row.get(key, "")
                if nid and nid not in known_nodes and nid != "NEEDS_REVIEW":
                    orphans.append(f"  {key}='{nid}' in {path.name}")

    if orphans:
        return {
            "status": "FAIL",
            "message": f"{len(orphans)} orphan edge endpoint(s) — no matching node",
            "details": orphans[:15],
        }
    return {"status": "PASS", "message": "all edge endpoints have matching nodes", "details": []}


# ══════════════════════════════════════════════════════════════════════════════
# Check 4 — MeTTa syntax
# ══════════════════════════════════════════════════════════════════════════════

def check_metta_syntax(metta_dir: Path) -> dict:
    """Every non-comment, non-empty line in edge .metta files should be valid MeTTa."""
    if not metta_dir.exists():
        return {"status": "WARN", "message": f"MeTTa directory not found: {metta_dir}", "details": []}
    bad_lines: list = []
    # Valid patterns:
    #   (relation (type ID) (type ID))                  — core triple
    #   (property (relation (type ID) (type ID)) value) — property
    #   (stv ...)                                       — truth value
    triple_pat   = re.compile(r'^\([A-Za-z_]+ \([A-Za-z_]+ [A-Z0-9_]+\) \([A-Za-z_]+ [A-Z0-9_]+\)\)')
    property_pat = re.compile(r'^\([A-Za-z_]+ \(')
    stv_pat      = re.compile(r'^\(stv ')

    for path in metta_dir.rglob("edges_*.metta"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue
            if not (triple_pat.match(stripped) or property_pat.match(stripped) or stv_pat.match(stripped)):
                bad_lines.append(f"  {path.name}:{i}  → {stripped[:80]}")

    if bad_lines:
        return {
            "status": "WARN",
            "message": f"{len(bad_lines)} line(s) do not match expected MeTTa patterns",
            "details": bad_lines[:10],
        }
    return {"status": "PASS", "message": "all MeTTa lines follow the expected format", "details": []}


# ══════════════════════════════════════════════════════════════════════════════
# Check 5 — Duplicate rows
# ══════════════════════════════════════════════════════════════════════════════

def check_duplicates(neo4j_dir: Path) -> dict:
    """No duplicate (source_id, target_id, relation) tuples should exist in edge CSVs."""
    seen: dict    = defaultdict(list)
    duplicates: list = []

    for path in neo4j_dir.rglob("edges_*.csv"):
        for row in _read_csv(path):
            key = (row.get("source_id", ""), row.get("target_id", ""), row.get("relation", ""))
            seen[key].append(str(path.name))

    for key, occurrences in seen.items():
        if len(occurrences) > 1:
            duplicates.append(
                f"  ({key[0]}) → ({key[1]}) rel='{key[2]}'  ×{len(occurrences)}  in {sorted(set(occurrences))}"
            )

    if duplicates:
        return {
            "status": "WARN",
            "message": f"{len(duplicates)} duplicate edge row(s)",
            "details": duplicates[:10],
        }
    return {"status": "PASS", "message": "no duplicate edges found", "details": []}


# ══════════════════════════════════════════════════════════════════════════════
# Check 6 — Coverage report
# ══════════════════════════════════════════════════════════════════════════════

def coverage_report(neo4j_dir: Path, metta_dir: Path) -> dict:
    """Count nodes, edges, relation types, entity types, source papers."""
    node_counts:     dict = defaultdict(int)
    edge_counts:     dict = defaultdict(int)
    source_papers:   set  = set()
    id_sources:      dict = defaultdict(int)
    fuzzy_count      = 0
    standard_count   = 0

    for path in neo4j_dir.rglob("nodes_*.csv"):
        label = path.stem.replace("nodes_", "")
        for row in _read_csv(path):
            node_counts[label] += 1
            src = row.get("id_source", "")
            if src:
                id_sources[src] += 1
            cid = row.get("id", "")
            if _classify_id(cid) == "standard":
                standard_count += 1
            else:
                fuzzy_count += 1

    for path in neo4j_dir.rglob("edges_*.csv"):
        # Extract relation name from filename: edges_{source}_{relation}_{target}.csv
        parts = path.stem.split("_")[1:]   # drop "edges" prefix
        for row in _read_csv(path):
            edge_counts[path.stem.replace("edges_","")] += 1
            doc = row.get("source_paper", "")
            if doc:
                source_papers.add(doc)

    metta_edge_files = list(metta_dir.rglob("edges_*.metta")) if metta_dir.exists() else []
    metta_node_files = list(metta_dir.rglob("nodes_*.metta")) if metta_dir.exists() else []

    details = [
        f"  Node types  : {len(node_counts)}",
        f"  Total nodes : {sum(node_counts.values())}",
        f"    Standard IDs : {standard_count}",
        f"    Fuzzy IDs    : {fuzzy_count}",
        f"  Edge types  : {len(edge_counts)}",
        f"  Total edges : {sum(edge_counts.values())}",
        f"  Source papers: {len(source_papers)}  ({', '.join(sorted(source_papers)[:5])}{'...' if len(source_papers)>5 else ''})",
        f"",
        f"  Node type breakdown:",
    ]
    for label, count in sorted(node_counts.items(), key=lambda x: -x[1]):
        details.append(f"    {label:<30} {count}")
    details.append(f"")
    details.append(f"  Edge type breakdown:")
    for label, count in sorted(edge_counts.items(), key=lambda x: -x[1]):
        details.append(f"    {label:<50} {count}")
    details.append(f"")
    details.append(f"  ID source breakdown:")
    for src, count in sorted(id_sources.items(), key=lambda x: -x[1]):
        details.append(f"    {src:<20} {count}")
    details.append(f"")
    details.append(f"  Output files:")
    details.append(f"    Neo4j node CSVs : {len(list(neo4j_dir.rglob('nodes_*.csv')))}")
    details.append(f"    Neo4j edge CSVs : {len(list(neo4j_dir.rglob('edges_*.csv')))}")
    details.append(f"    Cypher files    : {len(list(neo4j_dir.rglob('*.cypher')))}")
    details.append(f"    MeTTa node files: {len(metta_node_files)}")
    details.append(f"    MeTTa edge files: {len(metta_edge_files)}")

    return {"status": "INFO", "message": "coverage summary", "details": details}


# ══════════════════════════════════════════════════════════════════════════════
# Report printer
# ══════════════════════════════════════════════════════════════════════════════

def _print_check(name: str, result: dict) -> bool:
    """Print a single check result. Returns True if it passed or is INFO/WARN."""
    status  = result["status"]
    message = result["message"]
    details = result.get("details", [])

    if status == "PASS":
        print(_pass(f"{name}: {message}"))
    elif status == "WARN":
        print(_warn(f"{name}: {message}"))
        for d in details:
            print(_info(d))
    elif status == "FAIL":
        print(_fail(f"{name}: {message}"))
        for d in details:
            print(_info(d))
    else:  # INFO
        print(f"\n{_BOLD}{name}{_RESET}")
        for d in details:
            print(d)

    return status != "FAIL"


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate bio-semantic-parser output files."
    )
    parser.add_argument("--neo4j-dir", default="data/kg_output/unified/neo4j",
                        help="Directory containing Neo4j CSV files")
    parser.add_argument("--metta-dir", default="data/kg_output/unified/metta",
                        help="Directory containing MeTTa files")
    parser.add_argument("--output",    default=None,
                        help="Write JSON report to FILE")
    args = parser.parse_args()

    neo4j_dir = Path(args.neo4j_dir)
    metta_dir = Path(args.metta_dir)

    print("\n" + "═" * 72)
    print(f"  BIO SEMANTIC PARSER — OUTPUT VALIDATION REPORT")
    print(f"  Neo4j dir : {neo4j_dir}")
    print(f"  MeTTa dir : {metta_dir}")
    print("═" * 72)

    if not neo4j_dir.exists():
        print(_warn(f"Neo4j directory not found: {neo4j_dir}"))
        print("  Run the full pipeline first to generate output files.")
        sys.exit(0)
    if not metta_dir.exists():
        print(_warn(f"MeTTa directory not found: {metta_dir}"))

    neo4j_csvs  = list(neo4j_dir.rglob("*.csv"))
    metta_files = list(metta_dir.rglob("*.metta"))
    print(f"\n  Found: {len(neo4j_csvs)} CSV file(s)  {len(metta_files)} MeTTa file(s)\n")

    if not neo4j_csvs and not metta_files:
        print(_warn("No output files found — nothing to validate."))
        sys.exit(0)

    all_passed = True
    results    = {}

    print(_head("CHECK 1 — Relation types (taxonomy enforcement)"))
    r = check_relation_types(neo4j_dir, metta_dir)
    results["relation_types"] = r
    if not _print_check("Relation types", r):
        all_passed = False

    print(_head("CHECK 2 — Entity ID format (standard databases)"))
    r = check_entity_ids(neo4j_dir)
    results["entity_ids"] = r
    if not _print_check("Entity IDs", r):
        all_passed = False

    print(_head("CHECK 3 — Orphan edges (referential integrity)"))
    r = check_orphan_edges(neo4j_dir)
    results["orphan_edges"] = r
    if not _print_check("Orphan edges", r):
        all_passed = False

    print(_head("CHECK 4 — MeTTa syntax"))
    r = check_metta_syntax(metta_dir)
    results["metta_syntax"] = r
    if not _print_check("MeTTa syntax", r):
        all_passed = False

    print(_head("CHECK 5 — Duplicate rows"))
    r = check_duplicates(neo4j_dir)
    results["duplicates"] = r
    if not _print_check("Duplicates", r):
        all_passed = False

    print(_head("CHECK 6 — Coverage report"))
    r = coverage_report(neo4j_dir, metta_dir)
    results["coverage"] = r
    _print_check("Coverage", r)

    print("\n" + "═" * 72)
    fail_count = sum(1 for v in results.values() if v["status"] == "FAIL")
    warn_count = sum(1 for v in results.values() if v["status"] == "WARN")

    if all_passed and warn_count == 0:
        print(f"  {_GREEN}{_BOLD}ALL CHECKS PASSED{_RESET}")
    elif all_passed:
        print(f"  {_YELLOW}{_BOLD}PASSED with {warn_count} warning(s){_RESET}  "
              f"— review fuzzy IDs and warnings above")
    else:
        print(f"  {_RED}{_BOLD}{fail_count} CHECK(S) FAILED{_RESET}  "
              f"— fix issues before importing to Neo4j or Atomspace")
    print("═" * 72 + "\n")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Convert sets to lists for JSON serialisation
        def _serialise(obj):
            if isinstance(obj, set):
                return list(obj)
            raise TypeError(type(obj))
        out.write_text(json.dumps(results, indent=2, default=_serialise), encoding="utf-8")
        print(f"  JSON report written to: {out}\n")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
