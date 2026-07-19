"""Layer 7 — Entity normalization, deduplication, semantic validation."""
import os
import sys
from pathlib import Path
from api.pipeline_utils import _emit, _log, _pre, _post, _ckpt


def run_layer7(emit, doc_id, _safe_id, results, tagged_chunks, output_format, _completed_layers):
    """Run post-extraction pipeline and return (processed, staging_db), or None on error."""
    def _skip(layer): return layer in _completed_layers

    # Pause after Layer 6 — vLLM KV cache drains to 0% at end of Layer 6 and freezes on the next request.
    import time as _time
    _time.sleep(float(os.getenv("LAYER_TRANSITION_DELAY", "8")))

    _pre(emit, 7)
    if _skip(7):
        _emit(emit, 7, "done", "Checkpoint — layer already complete ✓", {})
    else:
        _emit(emit, 7, "running", "Validating, deduplicating, checking contradictions…")
    try:
        staging_db = Path(f"data/staging/{_safe_id}_{output_format}.db")
        staging_db.parent.mkdir(parents=True, exist_ok=True)
        if not _skip(6) and not _skip(7):
            staging_db.unlink(missing_ok=True)
        os.environ["TRIPLE_STORE_PATH"] = str(staging_db)

        from src.postextraction.postextractor import process as postprocess
        pairs = list(zip(results, tagged_chunks))

        if not _skip(7):
            _l7_start = _time.time()

            def _step_cb(step, label, detail):
                elapsed = _time.time() - _l7_start
                msg = f"  Step {step}/7 — {label}" + (f": {detail}" if detail else "")
                _log(emit, 7, msg)
                sys.stderr.write(f"[Layer 7] {elapsed:.0f}s  {msg}\n")
                sys.stderr.flush()

            def _batch_cb(done, total, n_valid):
                elapsed = _time.time() - _l7_start
                sys.stderr.write(f"[Layer 7] {elapsed:.0f}s  Semantic validation batch {done}/{total} — {n_valid} VALID\n")
                sys.stderr.flush()
                _emit(emit, 7, "progress",
                      f"Semantic validation: batch {done}/{total} — {n_valid} VALID so far",
                      {"done": done, "total": total, "valid": n_valid})

            _n_rels = sum(len(r.relations) for r, _ in pairs if hasattr(r, "relations"))
            sys.stderr.write(f"[Layer 7] Starting — {len(pairs)} pairs / ~{_n_rels} relations to process\n")
            sys.stderr.write(f"[Layer 7] Computing confidence scores ({_n_rels} NLI passes) — this takes ~{max(5, _n_rels // 10)}s on CPU…\n")
            sys.stderr.flush()
            processed = postprocess(pairs, step_cb=_step_cb, batch_cb=_batch_cb)
            sys.stderr.write(f"[Layer 7] Done in {_time.time() - _l7_start:.0f}s\n")
            sys.stderr.flush()
        else:
            _l7_results_path = Path(f"data/checkpoints/{_safe_id}/layer7_processed.json")
            processed = []
            if _l7_results_path.exists():
                try:
                    import json as _jj7
                    processed = _jj7.loads(_l7_results_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

        n_valid  = sum(1 for r in processed if r.get("validation_verdict") == "VALID")
        n_dup    = sum(1 for r in processed if r.get("is_duplicate"))
        n_contra = sum(1 for r in processed if r.get("is_contradiction"))
        n_flag   = sum(1 for r in processed if r.get("flagged_for_review"))
        if not _skip(7):
            _log(emit, 7, f"Semantic validation: {n_valid} VALID, {n_dup} duplicates, {n_contra} contradictions, {n_flag} flagged")
            for r in processed[:15]:
                subj = r.get("subject_name", "")
                rel  = r.get("relation", "")
                obj  = r.get("object_name", "")
                v    = r.get("validation_verdict", "")
                conf = r.get("confidence", 0)
                _log(emit, 7, f"  {'✓' if v == 'VALID' else '⚑'} {subj} →{rel}→ {obj} ({conf:.2f}) [{v}]")

        _emit(emit, 7, "done", f"{n_valid} valid relations", {
            "valid":          n_valid,
            "duplicates":     n_dup,
            "contradictions": n_contra,
            "flagged":        n_flag,
            "relations": [{
                "subject":   r.get("subject_name", ""),
                "relation":  r.get("relation", ""),
                "object":    r.get("object_name", ""),
                "confidence":r.get("confidence", 0),
                "verdict":   r.get("validation_verdict", ""),
            } for r in processed[:50]],
        })
        # Do NOT call show_layer7() here — postprocess() already ran all 7 steps.
        _post(emit, 7, [
            f"{n_valid} relation(s) passed all 7 validation gates",
            f"{n_dup} duplicate(s) detected — confidence updated in existing triple",
            f"{n_contra} contradiction(s) flagged — opposing relation already in KG",
            f"{n_flag} flagged for human review — will not auto-insert",
            "Entity IDs normalized to MESH / NCBI Gene / ChEBI",
        ])
        try:
            import json as _jj7
            _l7_save = Path(f"data/checkpoints/{_safe_id}/layer7_processed.json")
            _l7_save.parent.mkdir(parents=True, exist_ok=True)
            _l7_save.write_text(_jj7.dumps(processed, default=str), encoding="utf-8")
        except Exception:
            pass
        _ckpt(doc_id, 7)
        return processed, staging_db
    except Exception as e:
        import traceback as _tb
        tb = _tb.format_exc()
        _log(emit, 7, f"  Full traceback:\n{tb[-600:]}", "warn")
        sys.stderr.write(f"[Layer 7] ERROR: {e}\n{tb[-800:]}\n")
        sys.stderr.flush()
        os.environ.pop("TRIPLE_STORE_PATH", None)
        _emit(emit, 7, "error", str(e))
        return None
