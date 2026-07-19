"""Routes: /api/file, /api/discard-paper, /api/checkpoint-status, /api/config, /api/resume-from-layer, /api/status."""
import os
import shutil
import sys
from pathlib import Path

from fastapi import APIRouter, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from api.run_state import _connections

_ROOT = Path(__file__).resolve().parents[2]

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

router = APIRouter()


@router.get("/api/file")
async def serve_file(path: str):
    path = path.split("?")[0]  # strip cache-busting ?t= query string
    if Path(path).is_absolute():
        import re as _re
        m = _re.search(r'/(data|frontend|config|src|tools|lib|tests|docs)/', path)
        if m:
            path = path[m.start() + 1:]
    p = Path(path)
    if not p.is_absolute():
        p = _ROOT / p
    p = p.resolve()
    if not p.exists() or not p.is_file():
        return JSONResponse({"error": f"File not found: {path}"}, status_code=404)
    try:
        p.relative_to(_ROOT.resolve())
    except ValueError:
        return JSONResponse({"error": "Access denied"}, status_code=403)

    if p.suffix.lower() == ".html":
        import re as _re
        content = p.read_text(encoding="utf-8", errors="replace")

        def _to_api(fpath: str) -> str:
            return "/api/file?path=" + fpath.replace("file://", "")

        content = _re.sub(
            r'(src|href|value)=(["\'])file://([^"\']+)\2',
            lambda m: f'{m.group(1)}={m.group(2)}{_to_api("file://" + m.group(3))}{m.group(2)}',
            content,
        )
        content = _re.sub(
            r"'(file:///[^']*)'",
            lambda m: f"'{_to_api(m.group(1))}'",
            content,
        )
        content = _re.sub(
            r'"(file:///[^"]*)"',
            lambda m: f'"{_to_api(m.group(1))}"',
            content,
        )
        def _strip_machine_prefix(m):
            prefix, abs_path = m.group(1), m.group(2)
            match = _re.search(r'/(data|frontend|config|src|tools|lib|tests|docs)/', abs_path)
            if match:
                return prefix + abs_path[match.start() + 1:]
            return m.group(0)
        content = _re.sub(
            r'(/api/file\?path=)((?:/[A-Za-z][^"\'&\s]*)?/(?:Users|home|root|mnt)/[^"\'&\s]+)',
            _strip_machine_prefix,
            content,
        )
        return HTMLResponse(content)

    return FileResponse(str(p))


@router.post("/api/discard-paper")
async def discard_paper(doc_id: str = Form(...)):
    """Delete all outputs for a paper so it can be reprocessed from scratch."""
    try:
        import sqlite3 as _sq
        kg_root = _ROOT / "data" / "kg_output"
        safe_id = doc_id.replace("/", "_").replace(":", "_")

        deleted_dirs = []
        for d in kg_root.glob(f"*{safe_id[:12]}*"):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                deleted_dirs.append(d.name)

        staging = _ROOT / "data" / "staging" / f"{safe_id}_both.db"
        if staging.exists(): staging.unlink()

        proc_db = _ROOT / "data" / "processed_ids.db"
        if proc_db.exists():
            try:
                con = _sq.connect(str(proc_db))
                con.execute("DELETE FROM processed_ids WHERE doc_id=?", (doc_id,))
                con.commit(); con.close()
            except Exception: pass

        for db_name in ["triple_store.db", "triple_store_neo4j.db", "triple_store_metta.db"]:
            db_path = _ROOT / "data" / db_name
            if db_path.exists():
                try:
                    con = _sq.connect(str(db_path))
                    con.execute("DELETE FROM triples WHERE source_papers LIKE ?", (f"%{doc_id}%",))
                    con.commit(); con.close()
                except Exception: pass

        ckpt_root = _ROOT / "data" / "checkpoints"
        for ck in ckpt_root.glob(f"{safe_id[:12]}*"):
            shutil.rmtree(ck, ignore_errors=True) if ck.is_dir() else ck.unlink()

        return {"ok": True, "deleted_dirs": deleted_dirs, "doc_id": doc_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/checkpoint-status")
async def checkpoint_status(doc_id: str = "", filename: str = ""):
    """Return checkpoint state so the frontend can show the layer selector before running."""
    try:
        import json as _j
        ckpt_root = _ROOT / "data" / "checkpoints"

        if doc_id:
            _safe = doc_id.replace("/", "_").replace(":", "_")
            ckpt  = ckpt_root / _safe / "meta.json"
            if ckpt.exists():
                meta       = _j.loads(ckpt.read_text())
                completed  = meta.get("completed_layers", [])
                next_layer = None if 8 in completed else next((l for l in range(3, 9) if l not in completed), None)
                return {"has_checkpoint": True, "completed_layers": completed,
                        "next_layer": next_layer, "doc_id": doc_id}

        if filename and ckpt_root.exists():
            fname_stem = filename.lower().replace(".pdf", "").replace(".txt", "")
            for meta_path in ckpt_root.glob("*/meta.json"):
                folder_name = meta_path.parent.name.lower()
                try:
                    meta       = _j.loads(meta_path.read_text())
                    stored_url = (meta.get("url") or "").lower()
                    if fname_stem in folder_name or folder_name in fname_stem or fname_stem in stored_url:
                        completed  = meta.get("completed_layers", [])
                        next_layer = None if 8 in completed else next((l for l in range(3, 9) if l not in completed), None)
                        found_id   = meta_path.parent.name
                        return {"has_checkpoint": True, "completed_layers": completed,
                                "next_layer": next_layer, "doc_id": found_id}
                except Exception:
                    continue

        return {"has_checkpoint": False}
    except Exception as exc:
        return {"has_checkpoint": False, "error": str(exc)}


@router.get("/api/config")
async def get_config():
    return {"enable_pln": os.getenv("ENABLE_PLN", "false").lower() == "true"}


@router.post("/api/resume-from-layer")
async def resume_from_layer(doc_id: str = Form(...), from_layer: int = Form(...)):
    """Reset checkpoint so pipeline resumes from from_layer on next run."""
    try:
        import json as _j
        _safe_doc = doc_id.replace("/", "_").replace(":", "_")
        ckpt_meta = _ROOT / "data" / "checkpoints" / _safe_doc / "meta.json"
        if not ckpt_meta.exists():
            return {"ok": True, "msg": "No checkpoint — pipeline will run from scratch"}

        meta           = _j.loads(ckpt_meta.read_text())
        old_layers     = meta.get("completed_layers", [])
        effective_from = max(from_layer, 3)
        reset_layers   = [l for l in old_layers if l >= effective_from]
        meta["completed_layers"] = [l for l in old_layers if l < effective_from]
        ckpt_meta.write_text(_j.dumps(meta, indent=2))

        ckpt_dir   = ckpt_meta.parent
        _layer_files = {
            3: "layer3_chunks.json",
            4: "layer4_annotated.json",
            6: "layer6_results.json",
            7: "layer7_processed.json",
        }
        deleted_files = []
        for l in reset_layers:
            fname = _layer_files.get(l)
            if fname:
                f = ckpt_dir / fname
                if f.exists():
                    f.unlink()
                    deleted_files.append(fname)

        return {
            "ok":            True,
            "from_layer":    from_layer,
            "kept_layers":   meta["completed_layers"],
            "reset_layers":  reset_layers,
            "deleted_files": deleted_files,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/status")
async def status():
    return {"status": "running", "active_runs": len(_connections)}
