"""Routes: /api/sources (CRUD) and /api/processed."""
import sys
from pathlib import Path

import yaml
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

_ROOT         = Path(__file__).resolve().parents[2]
_SOURCES_YAML = _ROOT / "config" / "sources.yaml"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

router = APIRouter()


@router.get("/api/sources")
async def list_sources():
    with open(_SOURCES_YAML) as f:
        cfg = yaml.safe_load(f)
    sources = cfg.get("sources", [])
    processed_db = _ROOT / "data" / "processed_ids.db"
    counts: dict = {}
    if processed_db.exists():
        import sqlite3
        try:
            conn = sqlite3.connect(str(processed_db))
            for row in conn.execute(
                "SELECT source_name, COUNT(*) FROM processed_ids GROUP BY source_name"
            ).fetchall():
                counts[row[0]] = row[1]
            conn.close()
        except Exception:
            pass
    return JSONResponse([
        {**s, "processed_count": counts.get(s["name"], 0)}
        for s in sources
    ])


@router.post("/api/sources")
async def add_source(
    name:        str = Form(...),
    source_type: str = Form("api"),
    fmt:         str = Form("xml"),
    base_url:    str = Form(""),
    id_field:    str = Form(""),
    rate_limit:  int = Form(5),
    api_key_env: str = Form(""),
    watch_dir:   str = Form(""),
):
    with open(_SOURCES_YAML) as f:
        cfg = yaml.safe_load(f)
    sources = cfg.get("sources", [])
    if any(s["name"] == name for s in sources):
        return JSONResponse({"error": f"Source '{name}' already exists."}, status_code=400)

    entry: dict = {
        "name":        name,
        "type":        source_type,
        "format":      fmt,
        "base_url":    base_url or None,
        "text_field":  None,
        "rate_limit":  rate_limit,
        "id_field":    id_field or None,
        "api_key_env": api_key_env or None,
        "search_query": "",
    }
    if source_type == "file":
        entry["watch_dir"] = watch_dir or f"data/{name}_inbox"

    sources.append(entry)
    cfg["sources"] = sources
    with open(_SOURCES_YAML, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    return JSONResponse({"ok": True, "source": entry})


@router.delete("/api/sources/{name}")
async def delete_source(name: str):
    with open(_SOURCES_YAML) as f:
        cfg = yaml.safe_load(f)
    before = len(cfg.get("sources", []))
    cfg["sources"] = [s for s in cfg.get("sources", []) if s["name"] != name]
    if len(cfg["sources"]) == before:
        return JSONResponse({"error": "Source not found."}, status_code=404)
    with open(_SOURCES_YAML, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    return JSONResponse({"ok": True})


@router.get("/api/processed")
async def list_processed():
    processed_db = _ROOT / "data" / "processed_ids.db"
    if not processed_db.exists():
        return JSONResponse([])
    import sqlite3
    try:
        conn = sqlite3.connect(str(processed_db))
        rows = conn.execute(
            "SELECT id, source_name, processed_at, format "
            "FROM processed_ids ORDER BY processed_at DESC LIMIT 100"
        ).fetchall()
        conn.close()
        papers = []
        for r in rows:
            doc_id   = r[0]
            src_name = r[1]
            proc_at  = r[2]
            fmt      = r[3] if len(r) > 3 else ""
            ckpt_dir = _ROOT / "data" / "checkpoints" / doc_id
            title    = doc_id[:40]
            if ckpt_dir.is_dir():
                meta = ckpt_dir / "meta.json"
                if meta.exists():
                    import json as _j
                    try: title = _j.loads(meta.read_text()).get("paper_title", title)
                    except Exception: pass
            papers.append({
                "doc_id":       doc_id,
                "title":        title,
                "source_name":  src_name,
                "processed_at": proc_at,
                "format":       fmt,
            })
        return JSONResponse(papers)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
