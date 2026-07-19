#!/usr/bin/env python3
"""
tools/export_unified.py
────────────────────────
Exports the complete unified knowledge graph from the SQLite triple store
(data/triple_store.db) into a single set of CSV, MeTTa, and HTML files.

The triple store is updated every time a paper is processed — it is the
single source of truth for the accumulated knowledge graph across all papers.
Running this script generates a consistent, deduplicated export of everything.

Output:
  data/kg_output/unified/neo4j/   — Neo4j-importable CSVs + Cypher
  data/kg_output/unified/metta/   — MeTTa files for Hyperon Atomspace
  data/kg_output/unified/graph.html — Interactive knowledge graph viewer

Usage:
  python tools/export_unified.py
  python tools/export_unified.py --output data/my_kg
  python tools/export_unified.py --min-confidence 0.7   # filter by confidence
  python tools/export_unified.py --no-html              # skip graph render
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_DB_PATH = Path("data/triple_store.db")


# ── Read all triples from SQLite ──────────────────────────────────────────────

def load_triples(min_confidence: float = 0.0,
                 include_contradictions: bool = False,
                 fmt: str = "neo4j") -> list:
    """
    Load validated triples from the format-specific triple store.

    Args:
        fmt — "neo4j" reads from triple_store_neo4j.db
              "metta" reads from triple_store_metta.db
              anything else falls back to the legacy triple_store.db
    """
    from src.postextraction.deduplication import db_path_for_format
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    db = db_path_for_format(fmt)
    if not db.exists():
        if _DB_PATH.exists():
            db = _DB_PATH
        else:
            print(f"Triple store not found: {db}")
            print("Run the pipeline on at least one paper first.")
            return []

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM triples WHERE confidence >= ?"
    if not include_contradictions:
        query += " AND is_contradiction = 0"
    query += " ORDER BY confidence DESC, updated_at DESC"

    rows = conn.execute(query, (min_confidence,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ── Slug helpers ──────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "other").lower()).strip("_")


def _metta_id(cid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(cid)).strip("_").upper()


def _metta_val(v: str) -> str:
    if not v:
        return ""
    v = str(v).replace('"', "'").replace("\n", " ").strip()
    return f'"{v}"' if (" " in v or "(" in v) else v.replace(" ", "_")


# ── Neo4j CSV writer ──────────────────────────────────────────────────────────

def write_neo4j(triples: list, out_dir: Path) -> dict:
    """Write unified Neo4j CSV files from all triples."""
    import csv

    DELIMITER = "|"
    nodes: dict = defaultdict(dict)    # {type_slug: {id: row}}
    edges: dict = defaultdict(list)    # {(s_slug, rel, o_slug): [rows]}

    for t in triples:
        s_slug = _slug(t.get("subject_type", "other"))
        o_slug = _slug(t.get("object_type",  "other"))
        rel    = _slug(t.get("relation",      "related_to"))

        # Collect unique nodes
        for id_key, name_key, type_key, slug in [
            ("subject_id", "subject_name", "subject_type", s_slug),
            ("object_id",  "object_name",  "object_type",  o_slug),
        ]:
            cid = t.get(id_key, "") or ""
            if cid and cid not in nodes[slug]:
                nodes[slug][cid] = {
                    "id":          cid,
                    "name":        t.get(name_key, ""),
                    "entity_type": t.get(type_key, "OTHER"),
                    "id_source":   "",
                }

        sources = []
        try:
            sources = json.loads(t.get("source_papers", "[]"))
        except Exception:
            sources = [t.get("source_papers", "")]
        edges[(s_slug, rel, o_slug)].append({
            "source_id":     t.get("subject_id", ""),
            "source_name":   t.get("subject_name", ""),
            "target_id":     t.get("object_id", ""),
            "target_name":   t.get("object_name", ""),
            "relation":      t.get("relation", ""),
            "source_type":   t.get("subject_type", ""),
            "target_type":   t.get("object_type", ""),
            "confidence":    t.get("confidence", 0.0),
            "negated":       str(bool(t.get("negated", 0))).lower(),
            "species":       t.get("species", "") or "",
            "tissue":        t.get("tissue",  "") or "",
            "condition":     t.get("condition", "") or "",
            "effect_size":   t.get("effect_size", "") or "",
            "source_papers": json.dumps([s for s in sources if s]),
            "reasoning":     (t.get("reasoning", "") or "")[:300],
            "is_contradiction": str(bool(t.get("is_contradiction", 0))).lower(),
        })

    node_files, edge_files = [], []

    # ── Node files: {entity_type}/nodes_{entity_type}.csv ──────────────
    node_fields = ["id", "name", "entity_type", "id_source"]
    for slug, node_map in nodes.items():
        type_dir = out_dir / slug
        type_dir.mkdir(parents=True, exist_ok=True)
        csv_path = type_dir / f"nodes_{slug}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=node_fields, delimiter=DELIMITER, extrasaction="ignore")
            w.writeheader()
            for row in node_map.values():
                w.writerow(row)
        node_files.append(str(csv_path))
        _write_node_cypher(slug, csv_path, type_dir, DELIMITER)

    # ── Edge files: {source_type}/edges_{source}_{rel}_{target}.csv ────
    # Edge goes in the SOURCE entity type folder — no duplication.
    edge_fields = [
        "source_id", "source_name", "source_type",
        "target_id", "target_name", "target_type",
        "relation", "confidence", "negated",
        "species", "tissue", "condition", "effect_size",
        "source_papers", "reasoning", "is_contradiction",
    ]
    for (s_slug, rel, o_slug), rows in edges.items():
        fname    = f"edges_{s_slug}_{rel}_{o_slug}"
        type_dir = out_dir / s_slug
        type_dir.mkdir(parents=True, exist_ok=True)
        csv_path = type_dir / f"{fname}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=edge_fields, delimiter=DELIMITER, extrasaction="ignore")
            w.writeheader()
            for row in rows:
                w.writerow(row)
        edge_files.append(str(csv_path))
        _write_edge_cypher(rel.upper(), s_slug, o_slug, csv_path, type_dir, DELIMITER)

    return {
        "node_types": len(nodes),
        "edge_types": len(edges),
        "node_count": sum(len(v) for v in nodes.values()),
        "edge_count": sum(len(v) for v in edges.values()),
        "node_files": node_files,
        "edge_files": edge_files,
    }


def _write_node_cypher(label: str, csv_path: Path, out_dir: Path, delim: str) -> None:
    rel = csv_path.relative_to(out_dir.parent).as_posix()
    cypher = f"""CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE;

CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///{rel}' AS row FIELDTERMINATOR '{delim}' RETURN row",
    "MERGE (n:{label} {{id: row.id}})
     SET n.name = row.name, n.entity_type = row.entity_type",
    {{batchSize: 1000, parallel: true}}
) YIELD batches, total RETURN batches, total;
"""
    (out_dir / f"nodes_{label}.cypher").write_text(cypher, encoding="utf-8")


def _write_edge_cypher(relation: str, s: str, o: str,
                        csv_path: Path, out_dir: Path, delim: str) -> None:
    suffix = f"{s}_{relation.lower()}_{o}"
    rel    = csv_path.relative_to(out_dir.parent).as_posix()
    cypher = f"""CALL apoc.periodic.iterate(
    "LOAD CSV WITH HEADERS FROM 'file:///{rel}' AS row FIELDTERMINATOR '{delim}' RETURN row",
    "MATCH (s:{s} {{id: row.source_id}})
     MATCH (t:{o} {{id: row.target_id}})
     MERGE (s)-[r:{relation}]->(t)
     SET r.confidence = toFloat(row.confidence),
         r.negated    = row.negated,
         r.species    = row.species,
         r.source_papers = row.source_papers",
    {{batchSize: 1000}}
) YIELD batches, total RETURN batches, total;
"""
    (out_dir / f"edges_{suffix}.cypher").write_text(cypher, encoding="utf-8")


# ── MeTTa writer ──────────────────────────────────────────────────────────────

def write_metta(triples: list, out_dir: Path) -> dict:
    """Write unified MeTTa files from all triples."""
    nodes_by_type: dict  = defaultdict(dict)
    edges_by_type: dict  = defaultdict(list)

    for t in triples:
        s_slug = _slug(t.get("subject_type", "other"))
        o_slug = _slug(t.get("object_type",  "other"))
        rel    = _slug(t.get("relation",      "related_to"))

        s_id  = _metta_id(t.get("subject_id", ""))
        o_id  = _metta_id(t.get("object_id",  ""))
        s_name= t.get("subject_name", "")
        o_name= t.get("object_name",  "")

        if s_id and s_id not in nodes_by_type[s_slug]:
            nodes_by_type[s_slug][s_id] = {"name": s_name, "slug": s_slug}
        if o_id and o_id not in nodes_by_type[o_slug]:
            nodes_by_type[o_slug][o_id] = {"name": o_name, "slug": o_slug}

        edges_by_type[(s_slug, rel, o_slug)].append({
            "triple": f"({rel} ({s_slug} {s_id}) ({o_slug} {o_id}))",
            "t": t,
        })

    node_files, edge_files = [], []

    for slug, node_map in nodes_by_type.items():
        type_dir = out_dir / slug
        type_dir.mkdir(parents=True, exist_ok=True)
        path = type_dir / f"nodes_{slug}.metta"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"; Bio Semantic Parser — Unified KG — nodes_{slug}.metta\n\n")
            for mid, props in node_map.items():
                f.write(f"({props['slug']} {mid})\n")
                if props["name"]:
                    f.write(f'(name ({props["slug"]} {mid}) {_metta_val(props["name"])})\n')
            f.write("\n")
        node_files.append(str(path))

    for (s_slug, rel, o_slug), rows in edges_by_type.items():
        suffix  = f"{s_slug}_{rel}_{o_slug}"
        rel_dir = out_dir / suffix
        rel_dir.mkdir(parents=True, exist_ok=True)
        path = rel_dir / f"edges_{suffix}.metta"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"; Bio Semantic Parser — Unified KG — edges_{suffix}.metta\n\n")
            for row in rows:
                t      = row["t"]
                triple = row["triple"]
                conf   = t.get("confidence", 0.0)
                neg    = bool(t.get("negated", 0))
                sources = []
                try:
                    sources = json.loads(t.get("source_papers", "[]"))
                except Exception:
                    sources = [t.get("source_papers", "")]

                f.write(f"{triple}\n")
                f.write(f"(confidence {triple} {conf:.4f})\n")
                f.write(f"(negated {triple} {neg})\n")
                f.write(f"(stv {triple} {conf:.4f} 1.0)\n")
                for src in sources:
                    if src:
                        f.write(f"(source {triple} {_metta_val(src)})\n")
                for prop, key in [("species","species"),("tissue","tissue"),
                                   ("condition","condition"),("effect_size","effect_size")]:
                    val = t.get(key, "") or ""
                    if val:
                        f.write(f"({prop} {triple} {_metta_val(val)})\n")
                f.write("\n")
        edge_files.append(str(path))

    return {
        "node_types": len(nodes_by_type),
        "edge_types": len(edges_by_type),
        "node_files": node_files,
        "edge_files": edge_files,
    }


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(triples: list) -> None:
    from collections import Counter
    papers  = set()
    rels    = Counter()
    etypes  = Counter()
    for t in triples:
        try:
            for p in json.loads(t.get("source_papers", "[]")):
                if p:
                    papers.add(p)
        except Exception:
            pass
        rels[t.get("relation","?")] += 1
        etypes[t.get("subject_type","?")] += 1
        etypes[t.get("object_type","?")] += 1

    print(f"\n  Papers processed     : {len(papers)}")
    print(f"  Total triples in KG  : {len(triples)}")
    print(f"  Unique relation types: {len(rels)}")
    print(f"  Top relations:")
    for rel, cnt in rels.most_common(8):
        print(f"    {rel:<35} {cnt}")
    print(f"  Papers: {', '.join(sorted(papers))}")


def _write_metta_browser(metta_dir: Path, out_html: Path, n_triples: int) -> None:
    """Generate a simple HTML file-browser for the MeTTa unified atomspace."""
    files = sorted(metta_dir.rglob("*.metta"))
    rows = ""
    for f in files:
        rel  = f.relative_to(metta_dir)
        size = f.stat().st_size
        lines = sum(1 for _ in open(f, encoding="utf-8"))
        rows += (
            f"<tr>"
            f"<td style='color:#79c0ff;padding:6px 12px'>{rel}</td>"
            f"<td style='color:#8b949e;padding:6px 12px;text-align:right'>{lines} lines</td>"
            f"<td style='color:#8b949e;padding:6px 12px;text-align:right'>{size:,} bytes</td>"
            f"<td style='padding:6px 12px'>"
            f"<button onclick=\"loadFile('{f.resolve().as_uri()}','{rel}')\" "
            f"style='background:#21262d;border:1px solid #30363d;color:#c9d1d9;"
            f"padding:2px 10px;border-radius:4px;cursor:pointer;font-size:11px'>View</button>"
            f"</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>MeTTa Unified Atomspace</title>
<style>
body{{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',system-ui,sans-serif;
      display:flex;flex-direction:column;height:100vh;margin:0;overflow:hidden}}
#header{{background:#161b22;border-bottom:1px solid #30363d;padding:12px 20px;flex-shrink:0}}
#header h1{{color:#58a6ff;font-size:15px;margin:0}}
#header p{{color:#8b949e;font-size:12px;margin:4px 0 0}}
#main{{display:flex;flex:1;overflow:hidden}}
#sidebar{{width:420px;overflow-y:auto;border-right:1px solid #30363d}}
#viewer{{flex:1;overflow-y:auto;padding:20px;background:#0d1117}}
table{{width:100%;border-collapse:collapse}}
tr:hover td{{background:#161b22}}
#viewer pre{{color:#c9d1d9;font-size:12px;line-height:1.5;white-space:pre-wrap}}
#file-title{{color:#58a6ff;font-size:13px;font-weight:600;margin-bottom:12px}}
</style></head><body>
<div id="header">
  <h1>🔗 MeTTa Unified Atomspace</h1>
  <p>{n_triples} triples · {len(files)} file(s) — click any file to preview</p>
</div>
<div id="main">
  <div id="sidebar">
    <table><thead><tr>
      <th style="color:#8b949e;padding:8px 12px;text-align:left;border-bottom:1px solid #30363d">File</th>
      <th style="color:#8b949e;padding:8px 12px;border-bottom:1px solid #30363d">Lines</th>
      <th style="color:#8b949e;padding:8px 12px;border-bottom:1px solid #30363d">Size</th>
      <th style="color:#8b949e;padding:8px 12px;border-bottom:1px solid #30363d"></th>
    </tr></thead><tbody>{rows}</tbody></table>
  </div>
  <div id="viewer">
    <div id="file-title">Select a file to preview its MeTTa content</div>
    <pre id="file-content" style="color:#8b949e">No file selected.</pre>
  </div>
</div>
<script>
async function loadFile(uri, name) {{
  document.getElementById('file-title').textContent = name;
  try {{
    const r = await fetch(uri);
    const t = await r.text();
    document.getElementById('file-content').textContent = t;
  }} catch(e) {{
    document.getElementById('file-content').textContent = 'Could not load: ' + e;
  }}
}}
</script></body></html>"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")


# ── Programmatic API ─────────────────────────────────────────────────────────

def run_export(out_root: Path = None, min_confidence: float = 0.0,
               include_contradictions: bool = False,
               generate_html: bool = True,
               formats: str = "both",
               run_verification: bool = False) -> dict:
    """
    Export the unified KG programmatically.

    Args:
        formats — "neo4j", "metta", or "both"
                  Each format gets its own root directory:
                    neo4j → data/kg_output/unified_neo4j/
                    metta → data/kg_output/unified_metta/
                  Pass out_root to override.

    Returns:
        {
            "triples":       int,
            "neo4j_dir":     Path | None,
            "neo4j_html":    Path | None,   ← interactive graph for Neo4j
            "metta_dir":     Path | None,
            "metta_html":    Path | None,   ← file-browser page for MeTTa
            "html_path":     Path | None,   ← alias: neo4j_html (backwards compat)
            "neo4j":         {...},
            "metta":         {...},
        }
    """
    _KG_ROOT = Path("data/kg_output")
    neo4j_root = out_root or (_KG_ROOT / "unified_neo4j")
    metta_root  = out_root or (_KG_ROOT / "unified_metta")
    if out_root is not None:
        neo4j_root = metta_root = out_root

    if formats == "both":
        neo4j_triples = load_triples(min_confidence, include_contradictions, fmt="neo4j")
        metta_triples = load_triples(min_confidence, include_contradictions, fmt="metta")
        # Merge by (subject_id, relation, object_id, negated) — deduplicate across DBs
        _seen = {}
        for t in neo4j_triples + metta_triples:
            key = (t.get("subject_id"), t.get("relation"), t.get("object_id"), t.get("negated"))
            if key not in _seen:
                _seen[key] = t
        triples = list(_seen.values())
    else:
        triples = load_triples(min_confidence, include_contradictions,
                               fmt="neo4j" if formats == "neo4j" else "metta")
    if not triples:
        return {"triples": 0,
                "neo4j_dir": neo4j_root / "neo4j", "neo4j_html": None,
                "metta_dir": metta_root / "metta",  "metta_html": None,
                "html_path": None, "neo4j": {}, "metta": {}}

    neo_result   = {}
    metta_result = {}
    neo4j_html   = None
    metta_html   = None

    if formats in ("neo4j", "both"):
        neo4j_dir = neo4j_root / "neo4j"
        neo4j_dir.mkdir(parents=True, exist_ok=True)
        neo_result = write_neo4j(triples, neo4j_dir)

        if generate_html:
            neo4j_html = neo4j_root / "graph.html"
            try:
                result = subprocess.run(
                    [sys.executable, "tools/visualize_graph.py",
                     "--run-dir", str(neo4j_root),
                     "--output", str(neo4j_html),
                     "--kg-root", str(out_root)],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    neo4j_html = None
            except Exception:
                neo4j_html = None

    if formats in ("metta", "both"):
        metta_dir = metta_root / "metta"
        metta_dir.mkdir(parents=True, exist_ok=True)
        metta_result = write_metta(triples, metta_dir)

        if generate_html:
            # MeTTa gets TWO HTML files:
            #   graph.html  — same interactive graph as Neo4j (built from triples directly)
            #   files.html  — MeTTa file browser for viewing raw .metta content
            metta_html = metta_root / "graph.html"
            try:
                # The visualizer expects {run_dir}/neo4j/ — write a temp neo4j dir,
                # generate the graph, then remove the temp dir.
                _tmp_neo4j = metta_root / "neo4j"
                _tmp_neo4j.mkdir(parents=True, exist_ok=True)
                write_neo4j(triples, _tmp_neo4j)
                result = subprocess.run(
                    [sys.executable, "tools/visualize_graph.py",
                     "--run-dir", str(metta_root),
                     "--output", str(metta_html)],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    metta_html = None
                # Remove the temp neo4j dir — MeTTa unified doesn't need CSV files
                import shutil as _sh
                _sh.rmtree(_tmp_neo4j, ignore_errors=True)
            except Exception:
                metta_html = None

            try:
                _write_metta_browser(metta_dir, metta_root / "files.html", len(triples))
            except Exception:
                pass

    neo4j_ver_html = None
    metta_ver_html = None

    if run_verification:
        try:
            from tools.verify_kg import run_verification as _run_ver

            if formats in ("neo4j", "both") and neo4j_html:
                neo4j_ver_html = neo4j_root / "verification_report.html"
                neo4j_ver_json = neo4j_root / "verification_report.json"
                _run_ver(fetch_text=True,
                         out_html=neo4j_ver_html,
                         out_json=neo4j_ver_json)

            if formats in ("metta", "both") and metta_html:
                # MeTTa and Neo4j share the same triples — same verification data
                metta_ver_html = metta_root / "verification_report.html"
                metta_ver_json = metta_root / "verification_report.json"
                if neo4j_ver_html and neo4j_ver_html.exists():
                    # Reuse the same report rather than fetching PMC twice
                    import shutil as _sh
                    _sh.copy2(neo4j_ver_html, metta_ver_html)
                    _sh.copy2(neo4j_ver_json, metta_ver_json)
                else:
                    _run_ver(fetch_text=True,
                             out_html=metta_ver_html,
                             out_json=metta_ver_json)
        except Exception as _ve:
            pass   # verification is optional — don't abort export

    return {
        "triples":        len(triples),
        "neo4j_dir":      neo4j_root / "neo4j" if formats in ("neo4j", "both") else None,
        "neo4j_html":     neo4j_html,
        "neo4j_ver_html": neo4j_ver_html,
        "metta_dir":      metta_root / "metta" if formats in ("metta", "both") else None,
        "metta_html":     metta_html,
        "metta_ver_html": metta_ver_html,
        "html_path":      neo4j_html,   # backwards compatibility
        "neo4j":          neo_result,
        "metta":          metta_result,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the unified knowledge graph from the triple store."
    )
    parser.add_argument("--output",         default="data/kg_output/unified",
                        help="Output directory (default: data/kg_output/unified)")
    parser.add_argument("--min-confidence", type=float, default=0.0,
                        help="Minimum confidence to include (default: 0.0 = all)")
    parser.add_argument("--include-contradictions", action="store_true",
                        help="Include contradiction-flagged triples")
    parser.add_argument("--no-html",        action="store_true",
                        help="Skip graph.html generation")
    parser.add_argument("--db",             default="data/triple_store.db",
                        help="Path to SQLite triple store")
    args = parser.parse_args()

    global _DB_PATH
    _DB_PATH = Path(args.db)
    out_root = Path(args.output)

    print(f"\n{'═'*60}")
    print(f"  Bio Semantic Parser — Unified KG Export")
    print(f"  Triple store : {_DB_PATH}")
    print(f"  Output       : {out_root}")
    print(f"{'═'*60}")

    triples = load_triples(args.min_confidence, args.include_contradictions)
    if not triples:
        print("  No triples found. Process at least one paper first.")
        return

    print_summary(triples)

    neo4j_dir = out_root / "neo4j"
    metta_dir = out_root / "metta"
    neo4j_dir.mkdir(parents=True, exist_ok=True)
    metta_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  Writing Neo4j CSV…")
    neo_result = write_neo4j(triples, neo4j_dir)
    print(f"    {neo_result['node_count']} nodes ({neo_result['node_types']} types)  "
          f"{neo_result['edge_count']} edges ({neo_result['edge_types']} types)")

    print(f"  Writing MeTTa…")
    metta_result = write_metta(triples, metta_dir)
    print(f"    {len(metta_result['node_files'])} node files  "
          f"{len(metta_result['edge_files'])} edge files")

    if not args.no_html:
        print(f"  Generating graph.html…")
        try:
            result = subprocess.run(
                [sys.executable, "tools/visualize_graph.py",
                 "--run-dir", str(out_root),
                 "--output", str(out_root / "graph.html")],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"    ✓ open {out_root / 'graph.html'}")
            else:
                print(f"    ⚠ HTML generation failed: {result.stderr[:100]}")
        except Exception as exc:
            print(f"    ⚠ HTML skipped: {exc}")

    print(f"\n  ✓ Unified KG written to: {out_root.resolve()}")
    print(f"    Neo4j : {out_root / 'neo4j'}")
    print(f"    MeTTa : {out_root / 'metta'}")
    print(f"    Graph : {out_root / 'graph.html'}")
    print(f"\n  Run again after each new paper — the triple store accumulates everything.")


if __name__ == "__main__":
    main()
