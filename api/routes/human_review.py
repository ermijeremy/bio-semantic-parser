"""Routes: /api/human-review, /api/suggest-id, /api/human-review/action."""
import sys
from pathlib import Path

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

_ROOT = Path(__file__).resolve().parents[2]

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

router = APIRouter()


@router.get("/api/human-review")
async def get_human_review(run_dir: str = ""):
    import json as _json
    try:
        rdir = Path(run_dir)
        if not rdir.is_absolute(): rdir = _ROOT / rdir
        hr_path = rdir / "human_review.jsonl"
        if not hr_path.exists():
            return JSONResponse([])
        records = [_json.loads(l) for l in hr_path.read_text().splitlines() if l.strip()]
        pending = [r for r in records if r.get("status", "PENDING") == "PENDING"]
        return JSONResponse(pending)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _clean_entity_name(name: str) -> str:
    """Remove PDF extraction artifacts from entity names before ontology lookup."""
    import re as _re
    s = _re.sub(r'-\s+', '', name)
    s = _re.sub(r'\.\d+\s*$', '', s)
    s = _re.sub(r'\s+', ' ', s).strip()
    return s


@router.get("/api/suggest-id")
async def suggest_canonical_id(name: str = "", entity_type: str = ""):
    """Resolve a TEXT: entity to a canonical ID via the full normalization chain + LLM fallback."""
    if not name:
        return JSONResponse({"id": None})
    try:
        import re as _re, json as _json
        from src.postextraction.entity_normalization import normalize_entity

        clean  = _clean_entity_name(name)
        etype  = entity_type.upper() if entity_type else "GENE"
        result = normalize_entity(clean, etype, existing_id=None)
        canon  = result.get("canonical_id", "")
        source = result.get("id_source", "")

        if canon and not canon.startswith("TEXT:") and canon != "NEEDS_REVIEW":
            return JSONResponse({
                "id":            canon,
                "source":        source,
                "confidence":    "high",
                "verified":      True,
                "official_name": clean,
            })

        # Chain failed — ask LLM as last resort
        from src.llm_client import call_llm
        prompt = (
            f'You are a biomedical ontology expert. Provide the canonical ontology ID for this entity.\n'
            f'Entity name: "{clean}"\n'
            f'Respond ONLY with a valid JSON object:\n'
            f'{{"id": "<prefix:number>", "source": "<HGNC|MeSH|ChEBI|NCBIGene|UniProt|GO>", '
            f'"confidence": "<high|medium|low>", "full_name": "<official full name>"}}\n'
            f'Use prefix:number format (e.g. hgnc:7804, mesh:D002784, chebi:15422, ncbigene:4784).\n'
            f'If you are not confident, set confidence to "low" but still provide your best guess.\n'
            f'If it is clearly not a biomedical entity, return {{"id": null}}.'
        )
        text = call_llm([{"role": "user", "content": prompt}], max_tokens=150, temperature=0.0)
        if isinstance(text, str):
            text = text.strip()
        m = _re.search(r'\{[^}]+\}', text, _re.DOTALL)
        if not m:
            return JSONResponse({"id": None})
        data = _json.loads(m.group())
        if not data.get("id"):
            return JSONResponse({"id": None})
        data["verified"] = False
        if data.get("confidence") not in ("low",):
            data["confidence"] = "low"
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"id": None, "error": str(e)})


@router.post("/api/human-review/action")
async def review_action(
    run_dir:    str = Form(...),
    staging_db: str = Form(...),
    records:    str = Form(...),
    action:     str = Form(...),
):
    """Approve or reject human review triples."""
    import json as _json
    import threading as _thr
    try:
        recs    = _json.loads(records)
        hr_path = Path(run_dir)
        if not hr_path.is_absolute(): hr_path = _ROOT / hr_path
        hr_path = hr_path / "human_review.jsonl"

        sdb = Path(staging_db)
        if not sdb.is_absolute(): sdb = _ROOT / sdb

        def _rebuild_after_approve(sdb_path, run_dir_str):
            try:
                from src.postextraction.deduplication import commit_staging_to_main
                from tools.visualize_graph import build_graph_data, render_html
                from tools.verify_kg import run_verification
                from src.publish.output_layer import export_csvs_from_db

                for fmt in ("neo4j", "metta"):
                    _sdb_fmt = sdb_path.parent / sdb_path.name.replace("_both.db", f"_{fmt}.db")
                    _sdb_use = sdb_path if sdb_path.name.endswith("_both.db") else (
                        _sdb_fmt if _sdb_fmt.exists() else sdb_path)
                    if _sdb_use.exists():
                        try: commit_staging_to_main(str(_sdb_use), formats=fmt)
                        except Exception: pass

                _run_path = Path(run_dir_str)
                if not _run_path.is_absolute(): _run_path = _ROOT / _run_path

                if _run_path.exists() and sdb_path.exists():
                    try: export_csvs_from_db(str(sdb_path), str(_run_path), formats="neo4j")
                    except Exception: pass

                if _run_path.exists():
                    _neo4j_csv = _run_path / "neo4j"
                    if _neo4j_csv.exists():
                        try:
                            _n, _e = build_graph_data([_neo4j_csv])
                            render_html(_n, _e, _run_path / "graph.html", title="Paper Knowledge Graph")
                        except Exception: pass
                    try:
                        run_verification(fetch_text=True, formats="neo4j",
                            db_path=str(sdb_path) if sdb_path.exists() else None,
                            out_html=_run_path / "verification_report.html",
                            out_json=_run_path / "verification_report.json")
                    except Exception: pass
                    try:
                        run_verification(fetch_text=True, formats="metta",
                            db_path=str(sdb_path) if sdb_path.exists() else None,
                            out_html=_run_path / "verification_report_metta.html",
                            out_json=_run_path / "verification_report_metta.json")
                    except Exception: pass
            except Exception: pass

        def _delayed_rebuild(sdb_path, rdir):
            import time as _t; _t.sleep(3)
            _rebuild_after_approve(sdb_path, rdir)

        if action == "approve":
            from src.publish.human_review import approve_records
            n = approve_records(recs, str(sdb), hr_path)
            _thr.Thread(target=_delayed_rebuild, args=(sdb, run_dir), daemon=True).start()
            return JSONResponse({"ok": True, "approved": n})
        else:
            import json as _js
            now  = __import__('datetime').datetime.utcnow().isoformat()
            keys = {(r.get("subject_name",""), r.get("relation",""), r.get("object_name","")) for r in recs}
            if hr_path.exists():
                lines = []
                for line in hr_path.read_text().splitlines():
                    try:
                        e = _js.loads(line)
                        k = (e.get("subject_name",""), e.get("relation",""), e.get("object_name",""))
                        if k in keys:
                            e["status"] = "REJECTED"; e["reviewed_at"] = now
                    except Exception: pass
                    lines.append(_js.dumps(e) if isinstance(e, dict) else line)
                hr_path.write_text("\n".join(lines) + "\n")
            _thr.Thread(target=_delayed_rebuild, args=(sdb, run_dir), daemon=True).start()
            return JSONResponse({"ok": True, "rejected": len(recs)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
