"""Layer 2 — Deduplication check and resume logic."""
from pathlib import Path
from api.pipeline_utils import _emit, _log, _pre, _post, _ckpt, _count_run_edges, _load_ver_stats


def run_layer2(emit, doc_id, _safe_id, _completed_layers, output_format, scheduler):
    """Check KG for existing triples, handle resume and already-done cases.

    Returns True to continue pipeline, or None to stop (all done or error).
    """
    _pre(emit, 2)
    _emit(emit, 2, "running", "Checking if paper was already processed…")
    try:
        from src.postextraction.deduplication import count_triples_for_paper
        existing = count_triples_for_paper(doc_id)
        already  = existing > 0
        _emit(emit, 2, "done",
              f"Already processed — {existing} triples in KG" if already else "New paper — not in KG",
              {"already_processed": already, "existing_triples": existing, "doc_id": doc_id})
        _post(emit, 2, [
            f"Doc ID: {doc_id}",
            f"Status: {'Already in KG — loading existing outputs' if already else 'New paper — will process all layers'}",
        ])
        _ckpt(doc_id, 2)

        _kg_root      = Path("data/kg_output")
        _safe         = doc_id.replace('/', '_').replace(':', '_')
        _run_dirs_check = sorted(
            [d for d in _kg_root.glob(f"*{_safe[:12]}*")
             if d.is_dir() and (d / 'graph.html').exists()],
            reverse=True
        )
        _has_run_folder = bool(_run_dirs_check)
        _next_layer = (None if 8 in _completed_layers
                       else next((l for l in range(3, 9) if l not in _completed_layers), None))

        if _completed_layers or already or _has_run_folder:
            n_runs = len(_run_dirs_check)
            emit({"layer": 0, "status": "log",
                  "message": (f"  Found {n_runs} existing run(s) — "
                              f"{'resuming from Layer ' + str(_next_layer) if _next_layer else 'loading outputs'}"),
                  "data": {"kind": "text"}})

            _run_options = []
            for _rd in _run_dirs_check[:5]:
                _rd_graph = _rd / "graph.html"
                _rd_pln   = _rd / "pln" / "pln_graph.html"
                _rd_ver   = _rd / "verification_report.html"
                _run_options.append({
                    "run_dir":    str(_rd),
                    "run_name":   _rd.name,
                    "graph_html": str(_rd_graph) if _rd_graph.exists() else "",
                    "pln_html":   str(_rd_pln)   if _rd_pln.exists()   else "",
                    "ver_html":   str(_rd_ver)   if _rd_ver.exists()   else "",
                })

            _run = _run_dirs_check[0] if _run_dirs_check else None
            if _run:
                _layers_to_show_done = [l for l in [3, 4, 5, 6, 7, 8]
                                        if _next_layer is None or l < _next_layer]
                for layer in _layers_to_show_done:
                    _pre(emit, layer)
                    _emit(emit, layer, "done", "Loaded from existing run ✓", {})
                _graph_html = _run / "graph.html"
                _ver_html   = _run / "verification_report.html"
                _pln_html   = _run / "pln" / "pln_graph.html"
                _existing_data = {
                    "graph_html":       str(_graph_html) if _graph_html.exists() else "",
                    "pln_html":         str(_pln_html)   if _pln_html.exists()   else "",
                    "ver_html":         str(_ver_html)   if _ver_html.exists()   else "",
                    "run_dir":          str(_run),
                    "doc_id":           doc_id,
                    "staging_db":       "",
                    "neo4j_edges":      _count_run_edges(_run),
                    "neo4j_nodes":      0,
                    "metta_edges":      _count_run_edges(_run),
                    "metta_nodes":      0,
                    **_load_ver_stats(_run / "verification_report.json", _count_run_edges(_run)),
                    "pln_extracted":    existing or 2,
                    "pln_inferred":     0,
                    "existing_runs":    _run_options,
                    "n_runs":           n_runs,
                    "completed_layers": _completed_layers,
                    "next_layer":       _next_layer,
                }
                if not _next_layer:
                    _emit(emit, 8, "done", f"Existing outputs loaded ({n_runs} run(s) available)",
                          _existing_data)
                    return None  # pipeline complete, stop here
                emit({"layer": 0, "status": "log",
                      "message": (f"  Resuming from Layer {_next_layer} — "
                                  f"layers {_completed_layers} already done"),
                      "data": {"kind": "text", **_existing_data}})
        return True
    except Exception as e:
        _emit(emit, 2, "error", str(e))
        return None
