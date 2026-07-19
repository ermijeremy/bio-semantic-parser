"""Layer 1 — Source registry and checkpoint detection."""
from pathlib import Path
from api.pipeline_utils import _emit, _log, _pre, _post, _ckpt, _resolve_input


def run_layer1(emit, input_type, input_value, source_name, output_format, registry, scheduler):
    """Load registered sources, resolve the input to a doc_id, detect existing checkpoints.

    Returns a dict with layer-1 outputs, or None on error.
    """
    _pre(emit, 1)
    _emit(emit, 1, "running", "Loading registered data sources…")
    try:
        all_sources = registry.get_all_sources()
        source, doc_id, fetch_url = _resolve_input(
            input_type, input_value, source_name, all_sources, scheduler
        )
        paper_url = scheduler._build_paper_url(source, doc_id, fetch_url)
        source["_auto_detected"] = not bool(source_name)

        try:
            from api.rich_stream import capture_demo_output
            from tests.demo_pipeline import show_layer1
            capture_demo_output(show_layer1, registry, source, emit=emit, layer=1)
        except Exception:
            pass

        _safe_id         = doc_id.replace("/", "_").replace(":", "_")
        _ckpt_meta_path  = Path(f"data/checkpoints/{_safe_id}/meta.json")
        _staging_db_path = Path(f"data/staging/{_safe_id}_{output_format}.db")
        _completed_layers = []
        if _ckpt_meta_path.exists():
            try:
                import json as _j
                _meta      = _j.loads(_ckpt_meta_path.read_text())
                _raw       = _meta.get("completed_layers", [])
                _l6_claimed = any(l >= 6 for l in _raw)
                if _l6_claimed and not _staging_db_path.exists():
                    _completed_layers = [l for l in _raw if l < 6]
                    emit({"layer": 0, "status": "log",
                          "message": "  ⚠ Checkpoint stale (data cleared) — will re-run from Layer 6",
                          "data": {"kind": "text"}})
                else:
                    _completed_layers = _raw
            except Exception:
                pass
        if _completed_layers:
            emit({"layer": 1, "status": "log",
                  "message": f"  ✓ Checkpoint found — layers {_completed_layers} already done",
                  "data": {"kind": "text"}})

        _emit(emit, 1, "done", f"Source: {source['name']}", {
            "source_name":       source["name"],
            "source_type":       source.get("type", "api"),
            "source_format":     source.get("format", ""),
            "doc_id":            doc_id,
            "paper_url":         paper_url,
            "all_sources":       [{"name": s["name"], "type": s.get("type", ""),
                                   "format": s.get("format", "")} for s in all_sources],
            "completed_layers":  _completed_layers,
        })
        _post(emit, 1, [
            f"Source selected: {source['name']} ({source.get('format', '?').upper()})",
            f"Doc ID: {doc_id}",
            f"Paper URL: {paper_url}",
            f"{len(all_sources)} data sources registered",
        ])
        _ckpt(doc_id, 1)
        return {
            "source":            source,
            "doc_id":            doc_id,
            "fetch_url":         fetch_url,
            "paper_url":         paper_url,
            "_safe_id":          _safe_id,
            "_completed_layers": _completed_layers,
        }
    except Exception as e:
        _emit(emit, 1, "error", str(e))
        return None
