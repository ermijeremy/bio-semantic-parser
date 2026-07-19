"""Routes: KG commit, rebuild, staging-info, run-graph-stats."""
import sys
from pathlib import Path

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

_ROOT = Path(__file__).resolve().parents[2]

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

router = APIRouter()


@router.post("/api/rebuild-all-compare")
async def rebuild_all_compare():
    """Regenerate compare pages for ALL run dirs using current unified KG state."""
    import threading as _t
    def _do():
        try:
            from tests.demo_showcase import _build_compare_page
            from tools.verify_kg import run_verification as _rv
            kg_root   = _ROOT / "data" / "kg_output"
            uni_neo4j = kg_root / "unified_neo4j"
            uni_metta = kg_root / "unified_metta"
            for _fmt, _udir in [("neo4j", uni_neo4j), ("metta", uni_metta)]:
                if (_udir / "graph.html").exists():
                    try:
                        _rv(fetch_text=True, formats=_fmt,
                            out_html=_udir / "verification_report.html",
                            out_json=_udir / "verification_report.json")
                    except Exception: pass
            for run in kg_root.iterdir():
                if not run.is_dir() or not (run / "graph.html").exists(): continue
                if run.name.startswith("unified"): continue
                try:
                    _build_compare_page(
                        run / "graph.html", uni_neo4j / "graph.html",
                        run.name, "Unified Neo4j", run / "compare_neo4j.html",
                        run_verify_json=run / "verification_report.json",
                        unified_verify_html=uni_neo4j / "verification_report.html",
                        fmt="neo4j")
                except Exception: pass
                if (uni_metta / "graph.html").exists():
                    try:
                        _build_compare_page(
                            run / "graph.html", uni_metta / "graph.html",
                            run.name, "Unified MeTTa", run / "compare_metta.html",
                            run_verify_json=run / "verification_report.json",
                            unified_verify_html=uni_metta / "verification_report.html",
                            fmt="metta")
                    except Exception: pass
        except Exception: pass
    _t.Thread(target=_do, daemon=True).start()
    return JSONResponse({"ok": True, "message": "Rebuilding all compare pages in background"})


@router.get("/api/run-graph-stats")
async def run_graph_stats(run_dir: str = ""):
    """Return current edge/node count from Neo4j CSVs + verification stats."""
    try:
        import csv as _csv, json as _json
        rpath = Path(run_dir)
        if not rpath.is_absolute(): rpath = _ROOT / rpath
        neo4j_dir = rpath / "neo4j"
        edges, nodes = set(), set()
        if neo4j_dir.exists():
            for f in neo4j_dir.glob("edges_*.csv"):
                with open(f, newline="", encoding="utf-8") as fh:
                    for row in _csv.DictReader(fh, delimiter="|"):
                        s = row.get("source_id", "").strip()
                        t = row.get("target_id", "").strip()
                        r = (row.get("label", "") or row.get("relation", "")).strip()
                        if s and t and r:
                            edges.add((s, r, t))
                            nodes.add(s); nodes.add(t)
        ver_json = rpath / "verification_report.json"
        verified = total = partial = mismatched = 0
        if ver_json.exists():
            try:
                recs = _json.loads(ver_json.read_text())
                if isinstance(recs, list):
                    total     = len(recs)
                    verified  = sum(1 for r in recs if r.get("overall_status") == "CONFIRMED")
                    partial   = sum(1 for r in recs if r.get("overall_status") == "PARTIAL")
                    mismatched = sum(1 for r in recs if r.get("overall_status") == "MISMATCH")
                elif isinstance(recs, dict):
                    verified   = recs.get("verified", 0)
                    total      = recs.get("total", 0)
                    mismatched = recs.get("mismatched", 0)
            except Exception: pass
        return JSONResponse({
            "edges": len(edges), "nodes": len(nodes),
            "verified": verified, "total": total,
            "partial": partial, "mismatched": mismatched,
        })
    except Exception as e:
        return JSONResponse({"edges": 0, "nodes": 0, "error": str(e)})


@router.get("/api/staging-info")
async def staging_info(staging_db: str = "", output_format: str = "both"):
    """Return pre-commit breakdown: n_staged / n_already / n_net_new."""
    import sqlite3 as _sq
    try:
        sdb = Path(staging_db)
        if not sdb.is_absolute(): sdb = _ROOT / sdb
        if not sdb.exists():
            return JSONResponse({"n_staged": 0, "n_already": 0, "n_net_new": 0})

        conn = _sq.connect(str(sdb))
        rows = conn.execute(
            "SELECT subject_id, relation, object_id, negated FROM triples WHERE flagged_for_review=0"
        ).fetchall()
        conn.close()
        n_staged = len(rows)

        from src.postextraction.deduplication import db_path_for_format
        n_already  = 0
        main_path  = db_path_for_format("neo4j" if output_format in ("neo4j", "both") else "metta")
        if main_path.exists():
            mc = _sq.connect(str(main_path))
            for row in rows:
                exists = mc.execute(
                    "SELECT 1 FROM triples WHERE subject_id=? AND relation=? AND object_id=? AND negated=?",
                    (row[0], row[1], row[2], row[3])
                ).fetchone()
                if exists: n_already += 1
            mc.close()

        return JSONResponse({
            "n_staged":  n_staged,
            "n_already": n_already,
            "n_net_new": n_staged - n_already,
        })
    except Exception as e:
        return JSONResponse({"n_staged": 0, "n_already": 0, "n_net_new": 0, "error": str(e)})


@router.post("/api/commit_existing")
async def commit_existing_outputs(
    run_dir:       str = Form(""),
    doc_id:        str = Form(""),
    output_format: str = Form("both"),
):
    """Commit triples from an already-generated run folder to the unified atomspace."""
    try:
        import sqlite3 as _sq3, json as _jj
        kg_root = _ROOT / "data" / "kg_output"
        _run    = Path(run_dir) if run_dir else None
        total_new     = 0
        total_updated = 0
        neo4j_compare = ""
        metta_compare = ""

        if _run and _run.exists():
            from tools.visualize_graph import build_graph_data, render_html
            from tools.verify_kg import run_verification
            from tests.demo_showcase import _build_compare_page

            _safe_id = doc_id.replace('/', '_').replace(':', '_')
            _staging = _ROOT / "data" / "staging" / f"{_safe_id}_{output_format}.db"
            if _staging.exists():
                try:
                    from src.postextraction.deduplication import commit_staging_to_main
                    _cr      = commit_staging_to_main(str(_staging), formats=output_format)
                    total_new     = _cr.get("new", 0)
                    total_updated = _cr.get("updated", 0)
                except Exception: pass

            _main_db    = _ROOT / "data" / "triple_store_neo4j.db"
            run_triples = set()
            if (_run / "neo4j").exists():
                for csv in (_run / "neo4j").rglob("edges_*.csv"):
                    try:
                        import csv as _csv_mod
                        with open(csv, newline="", encoding="utf-8") as f:
                            for row in _csv_mod.DictReader(f, delimiter="|"):
                                s = row.get("source_id", "").strip()
                                o = row.get("target_id", "").strip()
                                r = row.get("label", "") or row.get("relation", "")
                                if s and o and r: run_triples.add((s, r.strip(), o))
                    except Exception: pass

            run_edge_count = len(run_triples)
            already_in_db  = 0
            if _main_db.exists() and run_triples:
                try:
                    conn = _sq3.connect(str(_main_db))
                    for (s, r, o) in run_triples:
                        if conn.execute(
                            "SELECT 1 FROM triples WHERE subject_id=? AND relation=? AND object_id=?",
                            (s, r, o)).fetchone():
                            already_in_db += 1
                    conn.close()
                except Exception: pass

            total_new     = max(0, run_edge_count - already_in_db)
            total_updated = already_in_db

            def _enrich_unified_csvs(neo4j_dir: Path):
                try:
                    import csv as _csv, json as _json
                    _ckpt_root = _ROOT / "data" / "checkpoints"
                    ch_map: dict = {}
                    for ckpt_file in _ckpt_root.rglob("layer7_processed.json"):
                        try:
                            for rec in _json.loads(ckpt_file.read_text(encoding="utf-8")):
                                key = (rec.get("subject_name",""), rec.get("relation",""), rec.get("object_name",""))
                                ch  = rec.get("confidence_channels")
                                if ch and isinstance(ch, dict):
                                    ch_map[key] = _json.dumps(ch)
                        except Exception: pass
                    if not ch_map: return
                    for csv_path in neo4j_dir.rglob("edges_*.csv"):
                        try:
                            rows = list(_csv.DictReader(csv_path.open(encoding="utf-8"), delimiter="|"))
                            if not rows: continue
                            changed = False
                            for row in rows:
                                if not row.get("confidence_channels") or row["confidence_channels"] == "{}":
                                    key = (row.get("source_name",""), row.get("relation",""), row.get("target_name",""))
                                    if key in ch_map:
                                        row["confidence_channels"] = ch_map[key]; changed = True
                            if changed:
                                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                                    w = _csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter="|")
                                    w.writeheader(); w.writerows(rows)
                        except Exception: pass
                except Exception: pass

            if output_format in ("neo4j", "both"):
                _neo4j_dir = kg_root / "unified_neo4j" / "neo4j"
                if _neo4j_dir.exists():
                    _enrich_unified_csvs(_neo4j_dir)
                    n, e = build_graph_data([_neo4j_dir])
                    render_html(n, e, kg_root / "unified_neo4j" / "graph.html", title="Unified Neo4j KG")
                    run_verification(fetch_text=False, formats="neo4j",
                        out_html=kg_root / "unified_neo4j" / "verification_report.html",
                        out_json=kg_root / "unified_neo4j" / "verification_report.json")

            if (_run / "graph.html").exists():
                if output_format in ("neo4j", "both"):
                    _cp = _run / "compare_neo4j.html"
                    _build_compare_page(
                        _run / "graph.html", kg_root / "unified_neo4j" / "graph.html",
                        "This Paper", "Unified Neo4j", _cp,
                        run_verify_json=_run / "verification_report.json",
                        unified_verify_html=kg_root / "unified_neo4j" / "verification_report.html",
                        fmt="neo4j")
                    neo4j_compare = str(_cp) if _cp.exists() else ""
                if output_format in ("metta", "both"):
                    _cm      = _run / "compare_metta.html"
                    _uni_metta = kg_root / "unified_metta" / "graph.html"
                    if _uni_metta.exists():
                        _build_compare_page(
                            _run / "graph.html", _uni_metta,
                            "This Paper", "Unified MeTTa", _cm,
                            run_verify_json=_run / "verification_report.json",
                            unified_verify_html=kg_root / "unified_metta" / "verification_report.html",
                            fmt="metta")
                        metta_compare = str(_cm) if _cm.exists() else ""

            def _rebuild_all_compare_pages():
                try:
                    for _fmt, _uni_dir in [("neo4j", kg_root / "unified_neo4j"),
                                           ("metta",  kg_root / "unified_metta")]:
                        if not (_uni_dir / "graph.html").exists(): continue
                        try:
                            run_verification(fetch_text=True, formats=_fmt,
                                out_html=_uni_dir / "verification_report.html",
                                out_json=_uni_dir / "verification_report.json")
                        except Exception: pass
                except Exception: pass
                try:
                    for _other_run in kg_root.iterdir():
                        if not _other_run.is_dir() or _other_run == _run: continue
                        _other_graph = _other_run / "graph.html"
                        if not _other_graph.exists(): continue
                        if output_format in ("neo4j", "both"):
                            _ocp = _other_run / "compare_neo4j.html"
                            try:
                                _build_compare_page(
                                    _other_graph, kg_root / "unified_neo4j" / "graph.html",
                                    _other_run.name, "Unified Neo4j", _ocp,
                                    run_verify_json=_other_run / "verification_report.json",
                                    unified_verify_html=kg_root / "unified_neo4j" / "verification_report.html",
                                    fmt="neo4j")
                            except Exception: pass
                        if output_format in ("metta", "both"):
                            _ocm  = _other_run / "compare_metta.html"
                            _uni_m = kg_root / "unified_metta" / "graph.html"
                            if _uni_m.exists():
                                try:
                                    _build_compare_page(
                                        _other_graph, _uni_m,
                                        _other_run.name, "Unified MeTTa", _ocm,
                                        run_verify_json=_other_run / "verification_report.json",
                                        unified_verify_html=kg_root / "unified_metta" / "verification_report.html",
                                        fmt="metta")
                                except Exception: pass
                except Exception: pass

            import threading as _thr_cp
            _thr_cp.Thread(target=_rebuild_all_compare_pages, daemon=True).start()

            from src.postextraction.deduplication import db_path_for_format as _db4f
            import sqlite3 as _sq3db
            _pdb = _db4f("neo4j")
            if _pdb.exists() and doc_id:
                _rows = []
                try:
                    _c = _sq3db.connect(str(_pdb)); _c.row_factory = _sq3db.Row
                    _rows = [dict(r) for r in _c.execute(
                        "SELECT * FROM triples WHERE source_papers LIKE ?",
                        (f"%{doc_id[:12]}%",)).fetchall()]; _c.close()
                except Exception: pass
                if _rows:
                    from src.publish.neo4j_writer import write as _nw2
                    _nw2(_rows, run_dir=_run)
                    n2, e2 = build_graph_data([_run / "neo4j"])
                    render_html(n2, e2, _run / "graph.html", title=_run.name)

        return {
            "ok":           True,
            "new":          total_new,
            "updated":      total_updated,
            "format":       output_format,
            "metta_compare": metta_compare,
            "neo4j_compare": neo4j_compare,
            "message": (f"{total_new} new · {total_updated} already in atomspace"
                        if total_new == 0 else
                        f"{total_new} new committed · {total_updated} already existed"),
        }
    except Exception as exc:
        import traceback
        return {"ok": False, "error": str(exc), "trace": traceback.format_exc()[:400]}


@router.post("/api/commit")
async def commit_to_atomspace(
    staging_db:    str = Form(...),
    output_format: str = Form("both"),
    doc_id:        str = Form(""),
):
    """Commit staging triples to the permanent unified atomspace."""
    import traceback as _tb
    try:
        _sdb = Path(staging_db)
        if not _sdb.is_absolute(): _sdb = _ROOT / _sdb
        if not _sdb.exists():
            return JSONResponse({"ok": False, "error": f"Staging DB not found: {_sdb}"}, status_code=404)

        from src.postextraction.deduplication import commit_staging_to_main
        _raw   = commit_staging_to_main(str(_sdb), formats=output_format)
        result = _raw if isinstance(_raw, dict) else {"new": 0, "updated": 0, "total": 0}

        neo4j_html = metta_html = neo4j_ver = metta_ver = ""
        kg_root    = _ROOT / "data" / "kg_output"

        try:
            import os as _os
            _old = _os.getcwd(); _os.chdir(str(_ROOT))
            from tools.export_unified import run_export
            run_export(generate_html=True, formats=output_format)
            _os.chdir(_old)
            nh = kg_root / "unified_neo4j" / "graph.html"
            mh = kg_root / "unified_metta"  / "graph.html"
            if nh.exists(): neo4j_html = str(nh)
            if mh.exists(): metta_html = str(mh)
        except Exception: pass

        try:
            from tools.verify_kg import run_verification
            if output_format in ("neo4j", "both"):
                _vr_dir = kg_root / "unified_neo4j"
                _vr_dir.mkdir(parents=True, exist_ok=True)
                _vh = _vr_dir / "verification_report.html"
                _vj = _vr_dir / "verification_report.json"
                run_verification(fetch_text=True, formats="neo4j", out_html=_vh, out_json=_vj)
                if _vh.exists(): neo4j_ver = str(_vh)
            if output_format in ("metta", "both"):
                _vr_dir = kg_root / "unified_metta"
                _vr_dir.mkdir(parents=True, exist_ok=True)
                _vh = _vr_dir / "verification_report.html"
                _vj = _vr_dir / "verification_report.json"
                run_verification(fetch_text=True, formats="metta", out_html=_vh, out_json=_vj)
                if _vh.exists(): metta_ver = str(_vh)
        except Exception: pass

        return JSONResponse({
            "ok":         True,
            "new":        result.get("new", 0),
            "updated":    result.get("updated", 0),
            "total":      result.get("total", 0),
            "format":     output_format,
            "neo4j_html": neo4j_html,
            "metta_html": metta_html,
            "neo4j_ver":  neo4j_ver,
            "metta_ver":  metta_ver,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "trace": _tb.format_exc()[-600:]}, status_code=500)


@router.post("/api/rebuild-compare")
async def rebuild_compare(run_dir: str = Form(...)):
    """Rebuild compare pages for a run directory using latest unified verification."""
    try:
        from tests.demo_showcase import _build_compare_page

        rdir = Path(run_dir)
        if not rdir.is_absolute(): rdir = _ROOT / rdir
        if not rdir.exists():
            return JSONResponse({"ok": False, "error": "Run dir not found"})

        kg_root       = _ROOT / "data" / "kg_output"
        run_html      = rdir / "graph.html"
        ver_html      = rdir / "verification_report.html"
        ver_json      = rdir / "verification_report.json"
        uni_neo4j     = kg_root / "unified_neo4j" / "graph.html"
        uni_metta     = kg_root / "unified_metta"  / "graph.html"
        uni_neo_ver   = kg_root / "unified_neo4j" / "verification_report.html"
        uni_metta_ver = kg_root / "unified_metta"  / "verification_report.html"

        try:
            from src.pipeline_checkpoint import get_paper_title as _gpt
            _parts  = rdir.name.split("_")
            _suffix = "_".join(_parts[2:]) if len(_parts) >= 3 else rdir.name
            _hash   = _suffix.removeprefix("PDF_")
            title   = _gpt(_hash) or _gpt(rdir.name) or _suffix.replace("_", " ")
            if title == _hash or (len(title) >= 32 and title.isalnum()):
                _ckpt_root = _ROOT / "data" / "checkpoints"
                if _ckpt_root.exists():
                    for _cd in _ckpt_root.iterdir():
                        if _cd.name.startswith(_hash[:8]):
                            _t = _gpt(_cd.name)
                            if _t and _t != _cd.name: title = _t
                            break
        except Exception:
            title = rdir.name

        edge_count = 0
        try:
            for _csv in rdir.rglob("neo4j/**/edges_*.csv"):
                with _csv.open() as _f:
                    edge_count += max(0, sum(1 for _ in _f) - 1)
        except Exception: pass

        neo4j_cmp = metta_cmp = ""
        if run_html.exists() and uni_neo4j.exists():
            out = rdir / "compare_neo4j.html"
            _build_compare_page(run_html, uni_neo4j,
                run_label=f"{title} — {edge_count} relation(s)",
                unified_label="Unified Neo4j KG",
                out_path=out,
                run_verify_html=ver_html      if ver_html.exists()      else None,
                unified_verify_html=uni_neo_ver if uni_neo_ver.exists() else None,
                run_verify_json=ver_json       if ver_json.exists()      else None)
            if out.exists(): neo4j_cmp = str(out)

        if uni_metta.exists():
            out = rdir / "compare_metta.html"
            _build_compare_page(
                run_html if run_html.exists() else uni_metta, uni_metta,
                run_label=f"{title} — {edge_count} relation(s)",
                unified_label="Unified MeTTa KG",
                out_path=out,
                run_verify_html=ver_html        if ver_html.exists()        else None,
                unified_verify_html=uni_metta_ver if uni_metta_ver.exists() else None,
                run_verify_json=ver_json         if ver_json.exists()        else None)
            if out.exists(): metta_cmp = str(out)

        return JSONResponse({"ok": True, "neo4j_compare": neo4j_cmp, "metta_compare": metta_cmp})
    except Exception as e:
        import traceback as _tb
        return JSONResponse({"ok": False, "error": str(e), "trace": _tb.format_exc()[-400:]})
