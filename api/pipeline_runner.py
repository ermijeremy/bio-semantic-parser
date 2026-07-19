"""Pipeline runner — web UI integration layer.

Thin orchestrator that calls each layer module in sequence and streams
structured progress events to the WebSocket server.
"""
import sys
import traceback
from pathlib import Path
from typing import Callable

from api.pipeline_utils import warm_models  # re-exported for api.app
from api.layers.layer1_registry  import run_layer1
from api.layers.layer2_dedup     import run_layer2
from api.layers.layer3_fetch     import run_layer3
from api.layers.layer4_ner       import run_layer4
from api.layers.layer5_schema    import run_layer5
from api.layers.layer6_extraction import run_layer6
from api.layers.layer7_postextract import run_layer7
from api.layers.layer8_publish   import run_layer8

__all__ = ["warm_models", "run_pipeline"]


def run_pipeline(
    input_type:    str,
    input_value:   str,
    output_format: str,
    emit:          Callable,
    run_id:        str,
    source_name:   str = "",
    is_stopped:    Callable = None,
):
    try:
        _run(input_type, input_value, output_format, emit, run_id, source_name,
             is_stopped=is_stopped or (lambda: False))
    except Exception as exc:
        emit({"layer": 0, "status": "fatal", "message": str(exc),
              "data": {"traceback": traceback.format_exc()}})


def _run(input_type, input_value, output_format, emit, run_id, source_name, is_stopped=None):
    _proj_root = str(Path(__file__).parent.parent)
    if _proj_root not in sys.path:
        sys.path.insert(0, _proj_root)

    if is_stopped is None:
        is_stopped = lambda: False

    def _check_stop(layer):
        if is_stopped():
            emit({"layer": layer, "status": "error", "message": "⬛ Stopped by user"})
            return True
        return False

    from src.scheduler.scheduler import Scheduler
    from src.registry.registry import SourceRegistry
    registry  = SourceRegistry()
    scheduler = Scheduler(registry)

    # Layer 1 — source registry + checkpoint detection
    l1 = run_layer1(emit, input_type, input_value, source_name, output_format, registry, scheduler)
    if l1 is None: return
    source, doc_id, fetch_url, paper_url = (l1["source"], l1["doc_id"],
                                             l1["fetch_url"], l1["paper_url"])
    _safe_id, _completed_layers = l1["_safe_id"], l1["_completed_layers"]
    if _check_stop(1): return

    # Layer 2 — deduplication + resume
    l2 = run_layer2(emit, doc_id, _safe_id, _completed_layers, output_format, scheduler)
    if l2 is None: return
    if _check_stop(2): return

    # Layer 3 — fetch + chunk
    l3 = run_layer3(emit, doc_id, _safe_id, fetch_url, source, paper_url, _completed_layers)
    if l3 is None: return
    chunks, title = l3
    if _check_stop(3): return

    # Layer 4 — NER ensemble
    tagged_chunks = run_layer4(emit, doc_id, _safe_id, chunks, _completed_layers)
    if tagged_chunks is None: return
    if _check_stop(4): return

    # Layer 5 — taxonomy schema
    if run_layer5(emit, doc_id, tagged_chunks, _completed_layers) is None: return
    if _check_stop(5): return

    # Layer 6 — LLM extraction
    results = run_layer6(emit, doc_id, _safe_id, tagged_chunks, _completed_layers)
    if results is None: return
    if _check_stop(6): return

    # Layer 7 — post-extraction (entity normalization, dedup, validation)
    l7 = run_layer7(emit, doc_id, _safe_id, results, tagged_chunks, output_format, _completed_layers)
    if l7 is None: return
    processed, staging_db = l7
    if _check_stop(7): return

    # Layer 8 — publish to KG + verification
    run_layer8(emit, doc_id, _safe_id, processed, tagged_chunks, staging_db, output_format, title)
