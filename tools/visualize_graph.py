#!/usr/bin/env python3
"""
tools/visualize_graph.py
─────────────────────────
Reads Neo4j CSV files and generates an interactive knowledge graph HTML.

Features (like Neo4j Browser):
  • Click node   → side panel: name, type, ID, all connected relations
  • Click edge   → side panel: subject → predicate → object, confidence,
                               species, condition, source paper, reasoning
  • Hover        → quick tooltip
  • Search box   → filter nodes by name
  • Legend       → node type / relation type colours
  • Dark theme   → same aesthetic as Neo4j Browser

Usage:
  python tools/visualize_graph.py                     # most recent run
  python tools/visualize_graph.py --all               # all runs merged
  python tools/visualize_graph.py --run-dir <path>
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


# ── Colour palette ─────────────────────────────────────────────────────────────

NODE_COLORS: dict = {
    "gene":                "#4F9CF9",
    "protein":             "#6366F1",
    "transcript":          "#818CF8",
    "rna":                 "#A78BFA",
    "genomic_variant":     "#C084FC",
    "small_molecule":      "#34D399",
    "drug":                "#10B981",
    "disease":             "#F87171",
    "cancer":              "#EF4444",
    "phenotype":           "#FBBF24",
    "symptom":             "#F59E0B",
    "pathway":             "#E879F9",
    "biological_process":  "#D946EF",
    "molecular_function":  "#A855F7",
    "cellular_component":  "#7C3AED",
    "tissue":              "#2DD4BF",
    "cell_type":           "#14B8A6",
    "cell_line":           "#0D9488",
    "organism":            "#FB7185",
    "enhancer":            "#F472B6",
    "other":               "#64748B",
}

EDGE_COLORS: dict = {
    "inhibits":            "#E74C3C",
    "downregulates":       "#E74C3C",
    "prevents":            "#E74C3C",
    "activates":           "#27AE60",
    "upregulates":         "#27AE60",
    "promotes":            "#2ECC71",
    "regulates":           "#F39C12",
    "deacetylates":        "#3498DB",
    "acetylates":          "#85C1E9",
    "phosphorylates":      "#2E86C1",
    "dephosphorylates":    "#A9CCE3",
    "methylates":          "#1A5276",
    "demethylates":        "#2471A3",
    "ubiquitinates":       "#154360",
    "sumoylates":          "#1B4F72",
    "binds_to":            "#8E44AD",
    "interacts_with":      "#9B59B6",
    "is_target_of":        "#7D3C98",
    "extends_lifespan":    "#1E8449",
    "reduces_lifespan":    "#922B21",
    "extends_healthspan":  "#239B56",
    "reduces_healthspan":  "#A93226",
    "treats":              "#2980B9",
    "palliates":           "#5DADE2",
    "biomarker_for":       "#16A085",
    "causes":              "#E67E22",
    "associates_with":     "#A569BD",
    "correlates_with":     "#BB8FCE",
    "predicts":            "#7FB3D3",
    "expressed_in":        "#45B39D",
    "participates_in":     "#76D7C4",
    "part_of":             "#48C9B0",
    "catalyzes":           "#F7DC6F",
    "secretes":            "#F0E68C",
    "infects":             "#FF6347",
    "_default":            "#7F8C8D",
}


def _parse_channels(raw) -> dict:
    """Parse confidence_channels from CSV cell (JSON string or dict)."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _node_color(entity_type: str) -> str:
    return NODE_COLORS.get(entity_type.lower(), NODE_COLORS["other"])


def _edge_color(relation: str) -> str:
    return EDGE_COLORS.get(relation.lower(), EDGE_COLORS["_default"])


def _display_name(entity_id: str, name: str) -> str:
    label = name or entity_id
    if label.startswith("TEXT:"):
        label = label[5:].replace("_", " ").title()
    return label


def _read_nodes(neo4j_dir: Path) -> dict:
    """Read all nodes_*.csv from any subfolder depth."""
    nodes = {}
    for csv_path in neo4j_dir.rglob("nodes_*.csv"):
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="|"):
                nid = row.get("id", "")
                if not nid:
                    continue
                props = {k: v for k, v in row.items() if v is not None}
                props.setdefault("entity_type", "OTHER")
                nodes[nid] = props
    return nodes


def _read_edges(neo4j_dir: Path) -> list:
    """
    Read all edges_*.csv from any subfolder depth.
    New structure: {entity_type}/edges_{relation}.csv
    Old structure: {entity_type}_{relation}_{target_type}/edges_*.csv
    Both work — we just rglob for edges_*.csv.
    """
    edges = []
    eid   = 0
    seen  = set()   # deduplicate (source_id, relation, target_id)
    for csv_path in neo4j_dir.rglob("edges_*.csv"):
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="|"):
                sid = row.get("source_id", "")
                tid = row.get("target_id", "")
                rel = row.get("relation", "related_to")
                if not sid or not tid:
                    continue
                key = (sid, rel, tid)
                if key in seen:
                    continue
                seen.add(key)
                eid += 1
                # CSV uses 'source_papers' (plural); 'source_paper' is the legacy single-paper field.
                # Value can be a raw hash string or a JSON-encoded array — normalize to a single ID.
                _sp_raw = row.get("source_paper", "") or row.get("source_papers", "")
                if _sp_raw.startswith("["):
                    try:
                        import json as _j; _sp = (_j.loads(_sp_raw) or [""])[0]
                    except Exception:
                        _sp = _sp_raw
                else:
                    _sp = _sp_raw
                edges.append({
                    "id":           eid,
                    "source_id":    sid,
                    "source_name":  row.get("source_name", ""),
                    "target_id":    tid,
                    "target_name":  row.get("target_name", ""),
                    "relation":     rel,
                    "confidence":   float(row.get("confidence", 0.0) or 0.0),
                    "negated":      row.get("negated", "false").lower() == "true",
                    "source_paper":  _sp,
                    "source_papers": row.get("source_papers", ""),
                    "section":       row.get("section", ""),
                    "species":       row.get("species", ""),
                    "tissue":        row.get("tissue", ""),
                    "condition":     row.get("condition", ""),
                    "effect_size":   row.get("effect_size", ""),
                    "reasoning":     row.get("reasoning", ""),
                    "validation":    row.get("validation_verdict", ""),
                    "review_reason": row.get("review_reason", ""),
                    "_paper":        _sp,
                    "_paper_url":    row.get("paper_url", ""),
                    "_source_name":  row.get("paper_source", ""),
                    "_conf_channels": _parse_channels(row.get("confidence_channels", "")),
                })
    return edges


def build_graph_data(neo4j_dirs: list) -> tuple:
    all_nodes: dict = {}
    all_edges: list = []
    for neo4j_dir in neo4j_dirs:
        if not neo4j_dir.exists():
            continue
        print(f"  Loading: {neo4j_dir}")
        nodes = _read_nodes(neo4j_dir)
        edges = _read_edges(neo4j_dir)
        all_nodes.update(nodes)
        all_edges.extend(edges)
    return all_nodes, all_edges


def render_html(nodes: dict, edges: list, output_path: Path, title: str,
                paper_meta: dict = None, papers_panel: list = None,
                fast_physics: bool = False) -> None:
    """
    Generate a rich interactive HTML graph with click panels.

    papers_panel: list of dicts with keys:
        paper_id, pct, n_conf, n_total, ver_html_uri, source_url
    When provided, adds a Papers tab to the header for the unified graph.
    """
    _vis_inline = (
        '<script src="/static/js/vis-network.min.js" '
        'onerror="this.onerror=null;this.src='
        "'https://unpkg.com/vis-network/standalone/umd/vis-network.min.js'\""
        '></script>'
    )

    degrees: dict = {}
    for e in edges:
        degrees[e["source_id"]] = degrees.get(e["source_id"], 0) + 1
        degrees[e["target_id"]] = degrees.get(e["target_id"], 0) + 1

    vis_nodes = []
    for nid, n in nodes.items():
        etype  = n.get("entity_type", "OTHER")
        name   = _display_name(nid, n.get("name", ""))
        color  = _node_color(etype)
        degree = degrees.get(nid, 0)
        type_label = etype.replace("_", " ").title()
        all_props = {k: v for k, v in n.items() if v is not None and str(v).strip()}

        vis_nodes.append({
            "id":    nid,
            "label": name,
            "title": f"{name} ({type_label})",
            "color": {"background": color,
                      "border": color,
                      "highlight": {"background": "#FFFFFF", "border": color},
                      "hover":     {"background": "#FFFFFF", "border": color}},
            "size":  max(18, 12 + degree * 5),
            "font":  {"color": "#ffffff", "size": 12, "face": "Inter, sans-serif",
                      "strokeWidth": 3, "strokeColor": "#00000066"},
            "shadow": {"enabled": True, "color": color + "88", "size": 16, "x": 0, "y": 0},
            "borderWidth": 2,
            "borderWidthSelected": 3,
            "_name":  name,
            "_type":  etype,
            "_props": all_props,
        })

    vis_edges = []
    for e in edges:
        rel     = e["relation"]
        neg     = e["negated"]
        # Human-approved: has review_reason (was flagged by Layer 7) but passed human review
        _review_reason = e.get("review_reason", "") or e.get("_review_reason", "")
        _verdict = e.get("validation", "") or e.get("_validation", "")
        _human   = bool(_review_reason) or _verdict in ("REVIEW", "REJECT")
        color   = "#888888" if neg else ("#F59E0B" if _human else _edge_color(rel))
        label   = ("✗ " if neg else "") + ("👤 " if _human else "") + rel.replace("_", " ")
        conf    = e["confidence"]
        vis_edges.append({
            "id":     e["id"],
            "from":   e["source_id"],
            "to":     e["target_id"],
            "label":  label,
            "title":  f"{rel} ({conf:.0%})",
            "color":  {"color": color + "cc", "highlight": "#ffffff", "hover": "#ffffff",
                       "opacity": 0.85},
            "width":  max(1.5, conf * 3.5),
            "dashes": neg,
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.6}},
            "font":   {"color": "#94A3B8", "size": 10, "align": "middle",
                       "face": "Inter, sans-serif",
                       "strokeWidth": 2, "strokeColor": "#00000088"},
            "shadow": {"enabled": True, "color": color + "55", "size": 8, "x": 0, "y": 0},
            "_relation":     rel,
            "_subject_name": _display_name(e["source_id"], e.get("source_name", "")),
            "_object_name":  _display_name(e["target_id"], e.get("target_name", "")),
            "_subject_id":   e["source_id"],
            "_object_id":    e["target_id"],
            "_confidence":   conf,
            "_negated":      neg,
            # source_paper may be empty when rebuilt from unified DB (uses source_papers JSON)
            # fall back to first entry of source_papers JSON array
            "_paper":        (e.get("source_paper", "") or
                              (__import__('json').loads(e.get("source_papers","[]") or "[]") or [""])[0]),
            "_section":      e.get("section", ""),
            "_species":      e.get("species", ""),
            "_tissue":       e.get("tissue", ""),
            "_condition":    e.get("condition", ""),
            "_effect_size":  e.get("effect_size", ""),
            "_reasoning":      e.get("reasoning", ""),
            "_validation":     e.get("validation", ""),
            "_conf_channels":  e.get("_conf_channels", {}),
        })

    shown_etypes = {n.get("entity_type", "OTHER") for n in nodes.values()}
    shown_rels   = {e["relation"] for e in edges}
    legend_nodes = [(t, NODE_COLORS.get(t.lower(), "#95A5A6"))
                    for t in sorted(shown_etypes)]
    legend_edges = [(r, _edge_color(r)) for r in sorted(shown_rels)]

    nodes_json = json.dumps(vis_nodes)
    edges_json = json.dumps(vis_edges)

    # ── Build doc_id → human title from checkpoints ──────────────────────────
    # Rule: PDF papers → filename without .pdf  (e.g. "Cell.pdf" → "Cell")
    #       Database papers → their ID          (e.g. "PMC6746067")
    _ckpt_root = Path(__file__).resolve().parent.parent / "data" / "checkpoints"
    _kg_root   = Path(__file__).resolve().parent.parent / "data" / "kg_output"
    _title_map: dict = {}
    if _ckpt_root.exists():
        for _mf in _ckpt_root.glob("*/meta.json"):
            try:
                _m    = json.loads(_mf.read_text())
                _did  = _m.get("doc_id", "")
                _src  = _m.get("source_name", "")
                _url  = _m.get("url", "")
                if not _did:
                    continue
                if _src == "pdf":
                    _fname = Path(_url).stem if _url else _m.get("paper_title", _did)
                    _label = _fname or _did
                    _title_map[_did] = _label
                    # Also map every source_paper DOI/ID that the DOI extractor
                    # produced from this PDF — found in the run folder CSV files.
                    # The run folder name contains the first 12 chars of the hash.
                    _hash_prefix = _did[:12]
                    for _run in sorted(_kg_root.glob(f"*_{_hash_prefix}*"), reverse=True):
                        for _csv in _run.rglob("edges_*.csv"):
                            try:
                                import csv as _csv_mod
                                with open(_csv, newline="", encoding="utf-8") as _cf:
                                    for _row in _csv_mod.DictReader(_cf, delimiter="|"):
                                        _sp = (_row.get("source_paper") or
                                               _row.get("source_papers") or "").strip()
                                        if _sp and _sp != _did:
                                            _title_map.setdefault(_sp, _label)
                            except Exception:
                                pass
                        break  # only most recent run needed
                else:
                    _title_map[_did] = _did
            except Exception:
                pass
    # Also add paper IDs from the unified DB that have no checkpoint
    _main_db = Path(__file__).resolve().parent.parent / "data" / "triple_store_neo4j.db"
    _kg_run_root = Path(__file__).resolve().parent.parent / "data" / "kg_output"
    if _main_db.exists():
        try:
            import sqlite3 as _sq, re as _re_db
            _c = _sq.connect(str(_main_db))
            for _row in _c.execute("SELECT DISTINCT source_papers FROM triples").fetchall():
                try:
                    _sps = json.loads(_row[0] or "[]")
                    for _sp in _sps:
                        if not _sp or _sp in _title_map: continue
                        if _re_db.match(r'^[0-9a-f]{32,}$', _sp):
                            # PDF hash with no checkpoint — use short hash as label
                            _title_map[_sp] = f"PDF·{_sp[:8]}"
                        elif not _sp.startswith("10."):
                            # Database paper (PMC, PMID) → use ID as label
                            _title_map[_sp] = _sp
                except Exception:
                    pass
            _c.close()
        except Exception:
            pass

    # Final fallback: any ID in the graph edges that co-occurs with a known title
    for _e in edges:
        _sp = _e.get("_paper", "")
        if not _sp:
            continue
        try:
            _ids = json.loads(_sp) if _sp.startswith("[") else [_sp]
        except Exception:
            _ids = [_sp]
        _found = next((_title_map[_i] for _i in _ids if _i in _title_map), None)
        if _found:
            for _i in _ids:
                _title_map.setdefault(_i, _found)
    _title_map_json = json.dumps(_title_map)

    _meta = paper_meta or {}
    if not _meta and edges:
        # Auto-collect from the first edge that has source info
        for _e in edges:
            if _e.get("_paper"):
                _meta.setdefault("doc_id",     _e.get("_paper", ""))
            if _e.get("_paper_url"):
                _meta.setdefault("paper_url",  _e.get("_paper_url", ""))
            if _e.get("_source_name"):
                _meta.setdefault("source",     _e.get("_source_name", ""))
            if _meta.get("doc_id"): break

    def _source_url(doc_id: str, source: str) -> str:
        import re as _re
        if not doc_id: return ""
        if doc_id.startswith("http"): return doc_id
        if _re.match(r"PMC\d+", doc_id, _re.I):
            return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{doc_id.upper()}/"
        if _re.fullmatch(r"\d{6,9}", doc_id):
            return f"https://pubmed.ncbi.nlm.nih.gov/{doc_id}/"
        if doc_id.startswith("10."):
            return f"https://doi.org/{doc_id}"
        if _re.match(r"GSE\d+", doc_id, _re.I):
            return f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={doc_id}"
        if _re.match(r"NCT\d+", doc_id, _re.I):
            return f"https://clinicaltrials.gov/study/{doc_id}"
        # SHA256 = local PDF — no external URL
        return ""

    def _display_id(doc_id: str) -> str:
        """Short display version of doc_id — use paper title from checkpoint if available."""
        if not doc_id: return "—"
        if doc_id in _title_map:
            return f"PDF · {_title_map[doc_id]}" if (len(doc_id) == 64 and doc_id.isalnum()) else _title_map[doc_id]
        if len(doc_id) == 64 and doc_id.isalnum():  # SHA256 with no title
            return f"PDF · {doc_id[:12]}…"
        return doc_id[:50]

    _doc_id     = _meta.get("doc_id", "")
    _paper_url  = _meta.get("paper_url", "") or _source_url(_doc_id, _meta.get("source",""))
    _src_name   = _meta.get("source", "").upper() or "—"
    _src_badge  = ""
    if _doc_id:
        _badge_text  = _display_id(_doc_id)
        _badge_color = "#2563eb" if "pmc" in _src_name.lower() else \
                       "#059669" if "pubmed" in _src_name.lower() else \
                       "#7c3aed" if "biorxiv" in _src_name.lower() or "medrxiv" in _src_name.lower() else \
                       "#0284c7" if "geo" in _src_name.lower() else \
                       "#d97706" if "clinical" in _src_name.lower() else \
                       "#6b7280"
        _open_link   = f"href='{_paper_url}' target='_blank'" if _paper_url else ""
        _src_badge   = (
            f"<a {_open_link} style='display:inline-flex;align-items:center;gap:6px;"
            f"background:{_badge_color}18;border:1px solid {_badge_color}44;"
            f"border-radius:6px;padding:4px 10px;text-decoration:none;color:{_badge_color};"
            f"font-size:11px;font-weight:600;font-family:monospace;transition:all .15s;' "
            f"onmouseover=\"this.style.background='{_badge_color}30'\" "
            f"onmouseout=\"this.style.background='{_badge_color}18'\">"
            f"<span style='opacity:.7'>{_src_name}</span>"
            f"<span>{_badge_text}</span>"
            + ("&nbsp;🔗" if _paper_url else "")
            + "</a>"
        )

    _papers_btn  = ""
    _papers_html = ""
    if papers_panel:
        _papers_btn = '<button id="papers-btn" onclick="togglePapersPanel()">📄 Papers (' + str(len(papers_panel)) + ')</button>'
        items = ""
        for p in papers_panel:
            pid   = p.get("paper_id","")
            pct   = p.get("pct", 0)
            nconf = p.get("n_conf", 0)
            ntot  = p.get("n_total", 0)
            ver   = p.get("ver_html_uri","")
            src   = p.get("source_url","")
            col   = "#3fb950" if pct >= 90 else ("#d29922" if pct >= 70 else "#f85149")
            items += f"""<div class="paper-item" onclick="filterByPaper('{pid}')">
  <div class="paper-id">{pid}</div>
  <div class="paper-score" style="color:{col}">{nconf}/{ntot} verified ({pct}%)</div>
  <div class="paper-actions">
    {"<a class='paper-link' href='" + ver + "' target='_blank'>✓ Verification</a>" if ver else ""}
    {"<a class='paper-link' href='" + src + "' target='_blank'>🔗 Source</a>" if src else ""}
  </div>
</div>"""
        _papers_html = f"""<div id="papers-panel">
  <div id="papers-panel-head">
    <h3>📄 Processed Papers</h3>
    <span style="cursor:pointer;color:#4a7fa5;font-size:16px" onclick="togglePapersPanel()">✕</span>
  </div>
  {items}
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
{_vis_inline}
<style>
  /* system font stack — no CDN dependency */
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ width: 100%; height: 100%; overflow: hidden; }}
  body {{ background: #060d1a; color: #e2e8f0; font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; display: flex; flex-direction: column; }}
  #header {{ background: linear-gradient(135deg, #0d1929 0%, #0f2136 100%); border-bottom: 1px solid #1a3350; padding: 0 20px; display: flex; align-items: center; gap: 14px; flex-shrink: 0; height: 52px; box-shadow: 0 2px 20px rgba(0,0,0,.5); }}
  #header h1 {{ font-size: 15px; font-weight: 700; color: #00c9b1; letter-spacing: -0.3px; }}
  #stats  {{ font-size: 12px; color: #4a7fa5; margin-left: auto; font-weight: 500; }}
  #search-box {{ background: #0d1f2f; border: 1px solid #1a3350; border-radius: 8px; padding: 6px 12px; color: #e2e8f0; font-size: 12px; width: 240px; font-family: inherit; transition: border-color .2s; }}
  #search-box:focus {{ outline: none; border-color: #00c9b1; box-shadow: 0 0 0 3px rgba(0,201,177,.15); }}
  #main {{ display: flex; height: calc(100vh - 52px); overflow: hidden; }}
  #graph-container {{ flex: 1; position: relative; height: calc(100vh - 52px); overflow: hidden; background: radial-gradient(ellipse at center, #0a1628 0%, #060d1a 70%); }}
  #network {{ width: 100%; height: calc(100vh - 52px); }}
  #side-panel {{ width: 360px; background: linear-gradient(180deg, #0d1929 0%, #0a1421 100%); border-left: 1px solid #1a3350; overflow-y: auto; flex-shrink: 0; transition: width 0.25s cubic-bezier(.4,0,.2,1); box-shadow: -4px 0 24px rgba(0,0,0,.4); }}
  #side-panel.hidden {{ width: 0; overflow: hidden; }}
  #panel-content {{ padding: 20px; }}
  #panel-title {{ font-size: 13px; font-weight: 700; color: #00c9b1; margin-bottom: 16px; border-bottom: 1px solid #1a3350; padding-bottom: 10px; display: flex; align-items: center; gap: 8px; letter-spacing: .3px; text-transform: uppercase; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 10px; font-weight: 700; letter-spacing: .5px; }}
  .field-group {{ margin-bottom: 16px; }}
  .field-label {{ font-size: 10px; color: #4a7fa5; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; font-weight: 600; }}
  .field-value {{ font-size: 12px; color: #cbd5e1; background: rgba(255,255,255,.04); padding: 8px 12px; border-radius: 8px; border: 1px solid #1a3350; word-break: break-word; line-height: 1.5; }}
  .field-value.canonical {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #38bdf8; }}
  .relation-row {{ background: rgba(255,255,255,.03); border: 1px solid #1a3350; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; cursor: pointer; transition: all .15s; }}
  .relation-row:hover {{ border-color: #00c9b1; background: rgba(0,201,177,.06); transform: translateX(2px); }}
  .relation-arrow {{ color: #00c9b1; font-size: 12px; }}
  .conf-bar {{ height: 3px; border-radius: 2px; background: #1a3350; margin-top: 6px; }}
  .conf-fill {{ height: 100%; border-radius: 2px; background: linear-gradient(90deg, #00c9b1, #4f9cf9); }}
  #placeholder {{ color: #2d5a80; font-size: 13px; text-align: center; padding: 60px 20px; }}
  #placeholder .icon {{ font-size: 48px; margin-bottom: 16px; opacity: .5; }}
  #legend {{ position: absolute; bottom: 16px; left: 16px; background: rgba(6,13,26,.88); border: 1px solid #1a3350; border-radius: 12px; padding: 12px 16px; font-size: 11px; max-width: 210px; backdrop-filter: blur(8px); }}
  #legend h4 {{ color: #4a7fa5; margin-bottom: 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; margin-bottom: 3px; color: #c9d1d9; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .legend-line {{ width: 20px; height: 3px; border-radius: 2px; flex-shrink: 0; }}
  #close-panel {{ cursor: pointer; color: #8b949e; font-size: 18px; margin-left: auto; }}
  #close-panel:hover {{ color: #e6edf3; }}
  .negated-badge {{ color: #f85149; font-size: 11px; }}
  #paper-filter {{ background: #0d1f2f; border: 1px solid #1a3350; border-radius: 8px; padding: 5px 10px; color: #e2e8f0; font-size: 12px; font-family: inherit; cursor: pointer; max-width: 220px; transition: border-color .2s; }}
  #paper-filter:focus {{ outline: none; border-color: #00c9b1; }}
  #paper-filter option {{ background: #0d1929; }}
  #papers-btn {{ background: rgba(0,201,177,.12); border: 1px solid rgba(0,201,177,.3); border-radius: 8px; padding: 5px 12px; color: #00c9b1; font-size: 12px; font-family: inherit; cursor: pointer; transition: all .2s; white-space: nowrap; }}
  #papers-btn:hover {{ background: rgba(0,201,177,.2); }}
  #papers-panel {{ position: fixed; top: 52px; right: 0; width: 320px; height: calc(100vh - 52px); background: linear-gradient(180deg,#0d1929 0%,#0a1421 100%); border-left: 1px solid #1a3350; overflow-y: auto; z-index: 100; transform: translateX(100%); transition: transform .3s cubic-bezier(.4,0,.2,1); box-shadow: -4px 0 24px rgba(0,0,0,.5); }}
  #papers-panel.open {{ transform: translateX(0); }}
  #papers-panel-head {{ padding: 16px 20px; border-bottom: 1px solid #1a3350; display: flex; align-items: center; justify-content: space-between; }}
  #papers-panel-head h3 {{ font-size: 12px; font-weight: 700; color: #00c9b1; text-transform: uppercase; letter-spacing: 1px; }}
  .paper-item {{ padding: 12px 16px; border-bottom: 1px solid #0f1f30; cursor: pointer; transition: background .15s; }}
  .paper-item:hover {{ background: rgba(0,201,177,.06); }}
  .paper-id {{ font-size: 12px; font-weight: 600; color: #e2e8f0; margin-bottom: 4px; }}
  .paper-score {{ font-size: 11px; margin-bottom: 6px; }}
  .paper-actions {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .paper-link {{ font-size: 10px; padding: 3px 8px; border-radius: 4px; border: 1px solid #1a3350; color: #4a7fa5; text-decoration: none; transition: all .15s; }}
  .paper-link:hover {{ border-color: #00c9b1; color: #00c9b1; }}
</style>
</head>
<body>

<div id="header">
  <span style="font-size:20px">🧬</span>
  <h1>{title}</h1>
  {_src_badge}
  <select id="paper-filter" onchange="filterByPaper(this.value)" title="Filter by source paper">
    <option value="">📄 All papers</option>
  </select>
  {_papers_btn}
  <input id="search-box" type="text" placeholder="Search nodes…" oninput="searchNodes(this.value)">
  <span id="stats">{len(nodes)} nodes · {len(edges)} edges</span>
</div>
{_papers_html}

<div id="main">
  <div id="graph-container">
    <div id="network"></div>
    <div id="legend">
      <h4>Node types</h4>
      {"".join(f'<div class="legend-item"><div class="legend-dot" style="background:{c}"></div>{t.replace("_"," ").title()}</div>' for t, c in legend_nodes[:10])}
      <h4 style="margin-top:8px">Edge width = confidence</h4>
      <h4>Dashed = negated</h4>
    </div>
  </div>

  <div id="side-panel" class="hidden">
    <div id="panel-content">
      <div id="placeholder">
        <div class="icon">👆</div>
        Click a <strong>node</strong> or <strong>edge</strong><br>to see details here
      </div>
    </div>
  </div>
</div>

<script>
// Debug: show error visually if vis fails
window.onerror = function(msg, src, line) {{
  var el = document.getElementById('network');
  if (el) el.innerHTML = '<div style="color:#f85149;padding:20px;font-family:monospace;font-size:13px">JS ERROR: ' + msg + '<br>Line: ' + line + '</div>';
}};
if (typeof vis === 'undefined') {{
  var el = document.getElementById('network');
  if (el) el.innerHTML = '<div style="color:#f85149;padding:20px;font-family:monospace;font-size:13px">ERROR: vis-network failed to load. Check network/CSP.</div>';
}}

const NODES_DATA = {nodes_json};
const EDGES_DATA = {edges_json};

function esc(s) {{
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

const nodeMap = {{}};
NODES_DATA.forEach(n => nodeMap[n.id] = n);
const edgeMap = {{}};
EDGES_DATA.forEach(e => edgeMap[e.id] = e);

// Global title map and label resolver — used by dropdown AND filterByPaper
const TITLE_MAP = {_title_map_json};
function paperLabel(p) {{
  if (TITLE_MAP[p]) return TITLE_MAP[p];
  if (/^[0-9a-f]{{64}}$/.test(p)) return 'PDF · ' + p.slice(0,12) + '…';
  return p.length > 40 ? p.slice(0,38)+'…' : p;
}}

// Populate paper filter dropdown — unique paper IDs only
(function() {{
  const seen = new Set();
  // Collect all source paper IDs from edges
  const allIds = new Set();
  EDGES_DATA.forEach(e => {{
    const p = e._paper || '';
    if (p.startsWith('[')) {{
      try {{ JSON.parse(p).forEach(x => {{ if (x.trim()) allIds.add(x.trim()); }}); return; }} catch(x) {{}}
    }}
    if (p.trim()) allIds.add(p.trim());
  }});
  // Deduplicate by label — keep only one representative ID per paper name
  const labelToId = new Map();
  allIds.forEach(id => {{
    const label = paperLabel(id);
    // Prefer hash IDs over DOIs as the representative — hashes are stable
    if (!labelToId.has(label) || /^[0-9a-f]{{64}}$/.test(id)) {{
      labelToId.set(label, id);
    }}
  }});
  const sel = document.getElementById('paper-filter');
  [...labelToId.keys()].sort().forEach(label => {{
    const opt = document.createElement('option');
    opt.value = label;   // use label as value so filter can match by name
    opt.textContent = '📄 ' + label;
    sel.appendChild(opt);
  }});
}})();

function filterByPaper(paperId) {{
  _focusedNode = null;
  if (!paperId) {{
    // Show all
    nodesDS.update(NODES_DATA.map(n => ({{id: n.id, hidden: false}})));
    edgesDS.update(EDGES_DATA.map(e => ({{id: e.id, hidden: false}})));
    return;
  }}
  // Match by paper label — any ID in the edge's source array that maps to this label
  function edgeMatchesPaper(e, label) {{
    const p = e._paper || '';
    if (!p) return false;
    const ids = p.startsWith('[') ? (()=>{{ try{{return JSON.parse(p)}}catch(x){{return [p]}} }})() : [p];
    return ids.some(id => paperLabel(id.trim()) === label);
  }}
  const visibleEdgeIds = new Set(
    EDGES_DATA.filter(e => edgeMatchesPaper(e, paperId)).map(e => e.id)
  );
  // Find nodes involved in those edges
  const visibleNodeIds = new Set();
  EDGES_DATA.forEach(e => {{
    if (visibleEdgeIds.has(e.id)) {{
      visibleNodeIds.add(e.from);
      visibleNodeIds.add(e.to);
    }}
  }});
  nodesDS.update(NODES_DATA.map(n => ({{id: n.id, hidden: !visibleNodeIds.has(n.id)}})));
  edgesDS.update(EDGES_DATA.map(e => ({{id: e.id, hidden: !visibleEdgeIds.has(e.id)}})));
  network.fit({{nodes: [...visibleNodeIds], animation: {{duration: 500, easingFunction: 'easeInOutQuad'}}}});
}}

// vis.js datasets
const nodesDS = new vis.DataSet(NODES_DATA);
const edgesDS = new vis.DataSet(EDGES_DATA);

let network;
function initNetwork() {{
  const container = document.getElementById('network');
  network = new vis.Network(container, {{nodes: nodesDS, edges: edgesDS}}, {{
  physics: {{
    barnesHut: {{
      gravitationalConstant: -12000,
      centralGravity: 0.1,
      springLength: 220,
      springConstant: 0.04,
      damping: 0.12,
      avoidOverlap: 0.3
    }},
    stabilization: {{iterations: {'80' if fast_physics else '300'}, updateInterval: 25}}
  }},
  interaction: {{
    hover: true,
    tooltipDelay: 200,
    navigationButtons: true,
    keyboard: true,
    zoomView: true,
    multiselect: false
  }},
  edges: {{
    smooth: {{type: 'dynamic', roundness: 0.3}},
    scaling: {{
      label: {{
        enabled: true,
        drawThreshold: 0.8,
        maxVisible: 16
      }}
    }}
  }},
  nodes: {{
    shape: 'dot',
    borderWidth: 2,
    scaling: {{
      label: {{
        enabled: true,
        min: 10,
        max: 18,
        drawThreshold: 0.4,
        maxVisible: 20
      }}
    }}
  }}
}});

// Auto-fit all nodes after stabilization completes
network.once('stabilizationIterationsDone', function() {{
  network.fit({{ animation: {{ duration: 600, easingFunction: 'easeInOutQuad' }} }});
  network.setOptions({{ physics: {{ enabled: false }} }});
}});

// ── Click node ──────────────────────────────────────────────────────────────
let _focusedNode = null;

function focusNode(nodeId) {{
  if (_focusedNode === nodeId) {{
    // second click on same node → restore full graph
    _focusedNode = null;
    nodesDS.update(NODES_DATA.map(n => ({{id: n.id, hidden: false}})));
    edgesDS.update(EDGES_DATA.map(e => ({{id: e.id, hidden: false}})));
    return;
  }}
  _focusedNode = nodeId;
  // Find all edges connected to this node
  const connectedEdgeIds = new Set(
    EDGES_DATA.filter(e => e.from === nodeId || e.to === nodeId).map(e => e.id)
  );
  // Find all neighbor node IDs
  const neighborIds = new Set([nodeId]);
  EDGES_DATA.forEach(e => {{
    if (e.from === nodeId) neighborIds.add(e.to);
    if (e.to   === nodeId) neighborIds.add(e.from);
  }});
  // Hide/show nodes and edges
  nodesDS.update(NODES_DATA.map(n => ({{id: n.id, hidden: !neighborIds.has(n.id)}})));
  edgesDS.update(EDGES_DATA.map(e => ({{id: e.id, hidden: !connectedEdgeIds.has(e.id)}})));
  // Fit view to visible nodes
  network.fit({{nodes: [...neighborIds], animation: {{duration: 400, easingFunction: 'easeInOutQuad'}}}});
}}

network.on('click', function(params) {{
  if (params.nodes.length > 0) {{
    const clickedId = params.nodes[0];
    if (_focusedNode && clickedId !== _focusedNode) {{
      // Already in focus mode — just show this node's panel, keep subgraph unchanged
      showNodePanel(clickedId);
    }} else {{
      // No focus OR clicking the focused node again → toggle focus
      focusNode(clickedId);
      showNodePanel(clickedId);
    }}
  }} else if (params.edges.length > 0) {{
    showEdgePanel(params.edges[0]);
  }} else {{
    // clicking empty space restores full graph
    if (_focusedNode) {{
      _focusedNode = null;
      nodesDS.update(NODES_DATA.map(n => ({{id: n.id, hidden: false}})));
      edgesDS.update(EDGES_DATA.map(e => ({{id: e.id, hidden: false}})));
    }}
    hidePanel();
  }}
}});

function showNodePanel(nodeId) {{
  const n = nodeMap[nodeId];
  if (!n) return;
  document.getElementById('side-panel').classList.remove('hidden');

  const outEdges  = EDGES_DATA.filter(e => e.from === nodeId);
  const inEdges   = EDGES_DATA.filter(e => e.to   === nodeId);
  const typeDisp  = n._type.replace(/_/g, ' ');
  const bg        = n.color.background;

  // ── Header: type badge only (name is a property, not the title) ──
  let html = `
    <div id="panel-title">
      <span style="width:12px;height:12px;border-radius:50%;background:${{bg}};
                   display:inline-block;flex-shrink:0"></span>
      <span class="badge" style="background:${{bg}}22;color:${{bg}};
            border:1px solid ${{bg}}44;padding:2px 10px;border-radius:10px">
        ${{typeDisp}}
      </span>
      <span id="close-panel" onclick="hidePanel()">✕</span>
    </div>
    <div style="font-size:10px;color:#4a7fa5;margin-bottom:12px;padding:6px 10px;background:rgba(0,201,177,.08);border-radius:6px;border:1px solid rgba(0,201,177,.2)">
      🔍 Showing subgraph — click node again or empty space to restore full graph
    </div>`;

  // ── Properties table — every column from the CSV row ──────────────
  const props = n._props || {{}};
  // Preferred display order for common columns; unknowns go after
  const ORDER = ['name','entity_type','id','id_source','needs_review'];
  const keys  = [
    ...ORDER.filter(k => props[k] !== undefined),
    ...Object.keys(props).filter(k => !ORDER.includes(k)).sort()
  ];

  html += `<div class="field-group">
    <div class="field-label">Properties</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
      <colgroup><col style="width:36%"><col style="width:64%"></colgroup>`;

  keys.forEach(k => {{
    const raw   = esc(props[k]);
    const label = esc(k.replace(/_/g,' '));
    const mono  = ['id','id_source'].includes(k);
    const color = mono ? '#79c0ff' : '#e6edf3';
    const font  = mono ? 'font-family:monospace;font-size:11px' : '';
    html += `<tr style="border-bottom:1px solid #21262d">
      <td style="padding:5px 8px 5px 0;color:#8b949e;vertical-align:top;
                 text-transform:capitalize">${{label}}</td>
      <td style="padding:5px 0;color:${{color}};${{font}};
                 word-break:break-all;vertical-align:top">${{raw}}</td>
    </tr>`;
  }});
  html += `</table></div>`;

  // ── Relations ──────────────────────────────────────────────────────
  if (outEdges.length > 0) {{
    html += `<div class="field-group">
      <div class="field-label">Outgoing (${{outEdges.length}})</div>`;
    outEdges.forEach(e => {{
      html += `<div class="relation-row" data-edge-id="${{e.id}}" style="cursor:pointer">
        <span class="relation-arrow">→</span>
        <strong style="color:${{e.color.color}}">${{e._relation.replace(/_/g,' ')}}</strong>
        ${{e._negated ? '<span class="negated-badge">[NEG]</span>' : ''}}
        <br><span style="color:#8b949e;font-size:11px">${{e._object_name}}</span>
        <div class="conf-bar"><div class="conf-fill" style="width:${{e._confidence*100}}%"></div></div>
      </div>`;
    }});
    html += `</div>`;
  }}

  if (inEdges.length > 0) {{
    html += `<div class="field-group">
      <div class="field-label">Incoming (${{inEdges.length}})</div>`;
    inEdges.forEach(e => {{
      html += `<div class="relation-row" data-edge-id="${{e.id}}" style="cursor:pointer">
        <span class="relation-arrow">←</span>
        <strong style="color:${{e.color.color}}">${{e._relation.replace(/_/g,' ')}}</strong>
        ${{e._negated ? '<span class="negated-badge">[NEG]</span>' : ''}}
        <br><span style="color:#8b949e;font-size:11px">${{e._subject_name}}</span>
        <div class="conf-bar"><div class="conf-fill" style="width:${{e._confidence*100}}%"></div></div>
      </div>`;
    }});
    html += `</div>`;
  }}

  document.getElementById('panel-content').innerHTML = html;
  // Use delegated listener — avoids inline onclick scope issues in iframes/innerHTML
  document.getElementById('panel-content').querySelectorAll('[data-edge-id]').forEach(el => {{
    el.addEventListener('click', () => showEdgePanel(parseInt(el.dataset.edgeId)));
  }});
}}

// ── Click edge ──────────────────────────────────────────────────────────────
function showEdgePanel(edgeId) {{
  const e = edgeMap[edgeId];
  if (!e) return;
  const panel = document.getElementById('side-panel');
  panel.classList.remove('hidden');

  const subjectNode = nodeMap[e.from] || {{}};
  const objectNode  = nodeMap[e.to]   || {{}};
  const subjColor   = (subjectNode.color || {{}}).background || '#888';
  const objColor    = (objectNode.color  || {{}}).background || '#888';
  const relColor    = e.color.color;

  const confPct = Math.round(e._confidence * 100);

  let html = `
    <div id="panel-title">
      <span style="color:${{relColor}};font-size:18px">⟶</span>
      Relation
      <span id="close-panel" onclick="hidePanel()">✕</span>
    </div>

    <div class="field-group">
      <div class="field-label">Triple (S → P → O)</div>
      <div class="field-value" style="line-height:1.8">
        <span style="background:${{subjColor}}22;color:${{subjColor}};padding:2px 6px;border-radius:4px;font-size:12px">
          ${{e._subject_name}}
        </span>
        <br>
        <span style="color:${{relColor}};font-weight:600;padding:2px 6px">
          ${{e._negated ? '✗ ' : ''}}${{e._relation.replace(/_/g,' ')}}
          ${{e._negated ? '<span class="negated-badge">[NEGATED]</span>' : ''}}
        </span>
        <br>
        <span style="background:${{objColor}}22;color:${{objColor}};padding:2px 6px;border-radius:4px;font-size:12px">
          ${{e._object_name}}
        </span>
      </div>
    </div>

    <div class="field-group">
      <div class="field-label" style="color:#8b949e;cursor:pointer;user-select:none;
           display:flex;align-items:center;justify-content:space-between"
           onclick="(function(el){{
             var d=el.closest('.field-group').querySelector('.conf-detail');
             var arrow=el.querySelector('.arr span:last-child');
             if(d.style.display==='none'){{d.style.display='block';arrow.textContent='▲';}}
             else{{d.style.display='none';arrow.textContent='▼';}}
           }})(this)"
           title="Click to see how this score was computed">
        Extraction confidence
        <span style="font-size:10px;color:#00c9b1;font-weight:600;
          border:1px solid #00c9b133;border-radius:4px;padding:2px 8px;
          background:#00c9b108;display:flex;align-items:center;gap:4px" class="arr">
          <span>How is this computed?</span><span>▼</span>
        </span>
      </div>
      <div class="field-value">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <span style="font-size:20px;font-weight:800;font-family:monospace;
            color:${{e._confidence>=0.75?'#238636':e._confidence>=0.55?'#d29922':'#8b949e'}}">
            ${{Math.round(e._confidence*100)}}%
          </span>
          <div style="flex:1">
            <div style="background:#21262d;border-radius:3px;height:6px">
              <div style="background:${{e._confidence>=0.75?'#238636':e._confidence>=0.55?'#d29922':'#8b949e'}};
                height:6px;border-radius:3px;width:${{Math.round(e._confidence*100)}}%"></div>
            </div>
            <div style="font-size:10px;color:#484f58;margin-top:3px">5-channel score · Layer 7</div>
          </div>
        </div>

        <!-- C1-C5 expandable breakdown -->
        <div class="conf-detail" style="display:none;background:#0d1117;border-radius:8px;
          padding:12px;border:1px solid #21262d;font-size:11px">
          <div style="color:#8b949e;font-size:10px;font-weight:700;letter-spacing:.06em;
            text-transform:uppercase;margin-bottom:10px">How the score is computed</div>

          ${{(function() {{
            const ch = e._conf_channels || {{}};
            const channels = [
              ['C1', 'Section weight',        ch.C1_section_weight,        0.20,
               'Results/Tables=100% · Abstract=60% · Discussion=40% · Methods=20%'],
              ['C2', 'Factuality (NLI)',       ch.C2_factuality_nli || ch.C2_factuality, 0.30,
               '"demonstrated"=95% · "suggests"=75% · "may"=50% · "failed to"=20%'],
              ['C3', 'Quantitative evidence',  ch.C3_quantitative_evidence, 0.25,
               'p≤0.001=100% · p≤0.05=75% · fold-change/OR=70% · none=40%'],
              ['C4', 'Direct co-sentence',     ch.C4_direct_claim,          0.15,
               'Both entities in same sentence=90% · inferred across sentences=35%'],
              ['C5', 'NLI entailment',         ch.C5_nli_entailment || ch.C5_llm_reliability, 0.10,
               'Does the source sentence support the extracted relation?'],
            ];
            return channels.map(([id, label, val, weight, desc]) => {{
              const v = val != null ? val : null;
              const pct = v != null ? Math.round(v * 100) : null;
              const wPct = Math.round(weight * 100);
              const clr = v == null ? '#484f58' : v >= 0.75 ? '#238636' : v >= 0.5 ? '#d29922' : '#f85149';
              const bar = v != null ? `<div style="background:#21262d;border-radius:2px;height:4px;margin-top:4px;width:100%">
                <div style="background:${{clr}};height:4px;border-radius:2px;width:${{pct}}%"></div></div>` : '';
              return `<div style="padding:8px 10px;background:#161b22;border-radius:6px;margin-bottom:6px">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px">
                  <span style="color:#58a6ff;font-weight:700;font-family:monospace">${{id}}</span>
                  <span style="color:#c9d1d9;font-size:11px">${{label}}</span>
                  <span style="color:${{clr}};font-weight:700;font-family:monospace;margin-left:auto;padding-left:8px">
                    ${{pct != null ? pct + '%' : '—'}}
                  </span>
                  <span style="color:#484f58;font-size:10px;margin-left:6px">w=${{wPct}}%</span>
                </div>
                <div style="color:#484f58;font-size:10px;line-height:1.4">${{desc}}</div>
                ${{bar}}
              </div>`;
            }}).join('');
          }})()}}

          <div style="color:#484f58;font-size:10px;margin-top:8px;padding-top:8px;border-top:1px solid #21262d">
            Combined via Open Targets weighted harmonic sum (Ochoa et al. NAR 2021)
          </div>
        </div>
      </div>
    </div>`;

  if (e._paper) html += `
    <div class="field-group">
      <div class="field-label">Source paper</div>
      <div class="field-value canonical">${{e._paper}}${{e._section ? '  ·  ' + e._section : ''}}</div>
    </div>`;

  const ctx = [e._species, e._tissue, e._condition, e._effect_size].filter(Boolean);
  if (ctx.length > 0) html += `
    <div class="field-group">
      <div class="field-label">Biological context</div>
      <div class="field-value">${{ctx.join('  ·  ')}}</div>
    </div>`;

  if (e._reasoning) html += `
    <div class="field-group">
      <div class="field-label">Reasoning trace (from extraction LLM)</div>
      <div class="field-value" style="font-style:italic;color:#c9d1d9">"${{e._reasoning}}"</div>
    </div>`;

  if (e._validation) html += `
    <div class="field-group">
      <div class="field-label">Semantic validation</div>
      <div class="field-value">
        <span class="badge" style="background:${{e._validation==='VALID'?'#238636':'#b62324'}}33;color:${{e._validation==='VALID'?'#3fb950':'#ff7b72'}};border:1px solid ${{e._validation==='VALID'?'#238636':'#b62324'}}55">
          ${{e._validation}}
        </span>
      </div>
    </div>`;

  html += `
    <div class="field-group">
      <div class="field-label">Subject canonical ID</div>
      <div class="field-value canonical">${{e._subject_id}}</div>
    </div>
    <div class="field-group">
      <div class="field-label">Object canonical ID</div>
      <div class="field-value canonical">${{e._object_id}}</div>
    </div>`;

  document.getElementById('panel-content').innerHTML = html;
  // Highlight the clicked edge
  network.selectEdges([edgeId]);
}}

function togglePapersPanel() {{
  const p = document.getElementById('papers-panel');
  if (p) p.classList.toggle('open');
}}

function hidePanel() {{
  document.getElementById('side-panel').classList.add('hidden');
  network.unselectAll();
}}

// ── Search ──────────────────────────────────────────────────────────────────
function searchNodes(query) {{
  if (!query) {{
    nodesDS.update(NODES_DATA.map(n => ({{id: n.id, hidden: false}})));
    return;
  }}
  const q = query.toLowerCase();
  nodesDS.update(NODES_DATA.map(n => ({{
    id: n.id,
    hidden: !n._name.toLowerCase().includes(q) && !n._type.toLowerCase().includes(q)
  }})));
}}

// Double-click → focus on node
network.on('doubleClick', function(params) {{
  if (params.nodes.length > 0) {{
    network.focus(params.nodes[0], {{scale: 1.5, animation: true}});
  }}
}});
  // Expose panel functions on window from INSIDE initNetwork where they are in scope.
  // These are defined as inner functions of initNetwork, so they must be exported here.
  window.showNodePanel = showNodePanel;
  window.showEdgePanel = showEdgePanel;
  window.hidePanel     = hidePanel;
  window.searchNodes   = searchNodes;
}} // end initNetwork

window.addEventListener('load', function() {{
  requestAnimationFrame(function() {{
    requestAnimationFrame(initNetwork);
  }});
}});
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize the bio-semantic-parser KG.")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output", default=None)
    parser.add_argument("--kg-root", default=None,
                        help="Path to data/kg_output — enables papers panel in unified graph")
    args = parser.parse_args()

    kg_root = Path(args.kg_root) if args.kg_root else Path("data/kg_output")

    if args.all:
        run_dirs = [d / "neo4j" for d in sorted(kg_root.iterdir())
                    if d.is_dir() and (d / "neo4j").exists()]
        title  = "Bio Semantic Parser — Complete Knowledge Graph"
        output = kg_root / "graph_all.html"
    elif args.run_dir:
        run_dirs = [Path(args.run_dir) / "neo4j"]
        title  = f"Bio Semantic Parser — {Path(args.run_dir).name}"
        output = Path(args.run_dir) / "graph.html"
    else:
        runs = sorted(
            [d for d in kg_root.iterdir() if d.is_dir() and (d / "neo4j").exists()],
            key=lambda d: d.name, reverse=True,
        )
        if not runs:
            print("No runs found. Run the pipeline first.")
            return
        run_dirs = [runs[0] / "neo4j"]
        title  = f"Bio Semantic Parser — {runs[0].name}"
        output = runs[0] / "graph.html"

    if args.output:
        output = Path(args.output)

    nodes, edges = build_graph_data(run_dirs)
    if not nodes:
        print("No nodes found.")
        return

    paper_meta = {}
    if args.run_dir:
        import sys as _sys; _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        try:
            from src.pipeline_checkpoint import get_paper_title as _gpt
            _ckpt_dir = Path(args.run_dir).resolve()
            # Try to find doc_id from verification JSON
            _vj = _ckpt_dir / "verification_report.json"
            if _vj.exists():
                import json as _j
                _recs = _j.loads(_vj.read_text())
                for _rec in _recs:
                    for _src in _rec.get("sources", []):
                        if _src.get("doc_id"):
                            paper_meta["doc_id"] = _src["doc_id"]
                            paper_meta["paper_url"] = _src.get("paper_url","") or _src.get("source_url","")
                            paper_meta["source"] = _src.get("paper_source","")
                            break
                    if paper_meta.get("doc_id"): break
        except Exception:
            pass

    print(f"\n  Graph: {len(nodes)} nodes  {len(edges)} edges")
    print(f"  Rendering → {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    render_html(nodes, edges, output, title, paper_meta=paper_meta)
    print(f"\n  ✓ Open: file://{output.resolve()}")
    print(f"    Or:  open {output}")


if __name__ == "__main__":
    main()
