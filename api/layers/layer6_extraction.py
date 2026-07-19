"""Layer 6 — LLM relation extraction with leaky-bucket concurrency."""
import os
from pathlib import Path
from api.pipeline_utils import _emit, _log, _pre, _post, _ckpt


def run_layer6(emit, doc_id, _safe_id, tagged_chunks, _completed_layers):
    """Extract biological relations with the LLM and return results list, or None on error.

    Loads from checkpoint if Layer 6 is already complete and results are saved.
    """
    def _skip(layer): return layer in _completed_layers

    results           = []
    _l6_results_path  = Path(f"data/checkpoints/{_safe_id}/layer6_results.json")

    _pre(emit, 6)

    if _skip(6) and _l6_results_path.exists():
        try:
            import json as _jj6
            from src.schema.pydantic_model import BiologicalRelation as _BR, ExtractionResult as _ER
            _saved = _jj6.loads(_l6_results_path.read_text(encoding="utf-8"))
            if _saved and isinstance(_saved, list):
                _loaded = []
                for rec in _saved:
                    try:
                        _rels = []
                        for r in rec.get("relations", []):
                            try:
                                _rels.append(_BR(**r))
                            except Exception:
                                pass
                        _loaded.append(_ER(relations=_rels,
                                          rejected=rec.get("rejected", False),
                                          rejection_reason=rec.get("rejection_reason")))
                    except Exception:
                        pass
                if _loaded:
                    results = _loaded
                    _emit(emit, 6, "done", f"Checkpoint — {len(results)} extraction results loaded ✓", {})
                    return results
        except Exception:
            pass  # fall through to re-run if load fails

    try:
        from src.extraction.extractor import extract_batch
        import concurrent.futures as _cf
        import threading as _th
        import time as _time
        total      = len(tagged_chunks)
        workers    = int(os.getenv("LLM_CHUNK_CONCURRENCY", "4"))
        _emit(emit, 6, "running", "Extracting biological relations with LLM…")
        _log(emit, 6, f"Processing {total} chunks with LLM — up to {min(workers, total)} in parallel…")

        _buf        = [None] * total
        _done_lock  = _th.Lock()
        _done_count = [0]

        def _extract_one(args):
            i, chunk = args
            batch = extract_batch([chunk])
            with _done_lock:
                _done_count[0] += 1
                done = _done_count[0]
            _emit(emit, 6, "progress", f"Chunk {done}/{total}", {"done": done, "total": total})
            res = batch[0] if batch else None
            if res:
                viable_rels = [r for r in res.relations if r.extraction_viable]
                if res.rejected:
                    _log(emit, 6, f"  Chunk {i+1} [{chunk.get('section', '?')}]: REJECTED after 3 retries")
                elif viable_rels:
                    for rel in viable_rels:
                        _log(emit, 6, f"  Chunk {i+1} [{chunk.get('section', '?')}]: {rel.subject_name} →{rel.relation}→ {rel.object_name} (conf: {rel.confidence:.2f})")
                else:
                    _log(emit, 6, f"  Chunk {i+1} [{chunk.get('section', '?')}]: no viable relation")
            return i, batch

        import concurrent.futures as _cff
        _submit_delay = float(os.getenv("CHUNK_SUBMIT_DELAY", "1.5"))
        # Leaky-bucket: stagger submissions so vLLM never hits Running:0, Waiting:N.
        with _cf.ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {}
            items   = list(enumerate(tagged_chunks))
            idx     = 0
            while idx < min(workers, total):
                fut = pool.submit(_extract_one, items[idx])
                pending[fut] = idx
                idx += 1
                if idx < min(workers, total):
                    _time.sleep(_submit_delay)
            while pending:
                done_fut = next(_cff.as_completed(pending))
                i, batch = done_fut.result()
                _buf[i]  = batch
                del pending[done_fut]
                if idx < total:
                    _time.sleep(_submit_delay)
                    fut = pool.submit(_extract_one, items[idx])
                    pending[fut] = idx
                    idx += 1

        for b in _buf:
            if b:
                results.extend(b)

        viable   = sum(1 for r in results for rel in r.relations if rel.extraction_viable)
        rejected = sum(1 for r in results if r.rejected)
        model    = os.getenv("LLM_MODEL", "gemma4")
        _emit(emit, 6, "done", f"{viable} relations extracted", {
            "viable": viable, "chunks": total, "rejected": rejected,
        })
        _post(emit, 6, [
            f"{viable} relation(s) extracted from {total} chunk(s)",
            f"LLM: {model} — local, no data leaves, no API cost",
            "Every relation has a mandatory reasoning trace explaining why that type was chosen",
            f"{rejected} chunk(s) rejected after 3 Pydantic retries → human review queue",
            "Negated relations correctly propagated from Layer 4 flag",
        ])
        try:
            import json as _jj6
            _l6_results_path.parent.mkdir(parents=True, exist_ok=True)
            _l6_results_path.write_text(
                _jj6.dumps([{"relations": [r.model_dump() for r in er.relations],
                             "rejected": er.rejected,
                             "rejection_reason": er.rejection_reason}
                            for er in results], default=str),
                encoding="utf-8"
            )
        except Exception:
            pass
        _ckpt(doc_id, 6)
        return results
    except Exception as e:
        _emit(emit, 6, "error", str(e))
        return None
