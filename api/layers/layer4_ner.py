"""Layer 4 — NER ensemble, negation detection, DOI / accession extraction."""
import os
from pathlib import Path
import api.pipeline_utils as _utils
from api.pipeline_utils import _emit, _log, _pre, _post, _ckpt


def run_layer4(emit, doc_id, _safe_id, chunks, _completed_layers):
    """Run NER ensemble over chunks and return tagged_chunks, or None on error.

    Loads from checkpoint if Layer 4 is already complete.
    """
    def _skip(layer): return layer in _completed_layers

    _l4_saved = Path(f"data/checkpoints/{_safe_id}/layer4_annotated.json")
    if _skip(4) and _l4_saved.exists():
        try:
            import json as _jj4
            _l4_data = _jj4.loads(_l4_saved.read_text(encoding="utf-8"))
            if _l4_data and isinstance(_l4_data, list):
                _pre(emit, 4)
                _emit(emit, 4, "done",
                      f"Checkpoint — {len(_l4_data)} tagged chunks loaded, NER skipped ✓",
                      {"chunks": len(_l4_data)})
                return _l4_data
        except Exception:
            pass  # fall through to re-run NER

    _pre(emit, 4)
    _emit(emit, 4, "running", "Tagging entities and detecting negation…")
    try:
        _m_names = [os.getenv(f"NER_MODEL_{i}", "").split("en_ner_")[-1].replace("_md", "").upper()
                    for i in range(1, 9) if os.getenv(f"NER_MODEL_{i}", "").strip()]
        _hf_name = (os.getenv("HF_NER_MODEL", "")
                    if os.getenv("HF_NER_ENABLED", "true").lower() == "true" else "")
        _all_names = " · ".join(_m_names + ([_hf_name.split("/")[-1]] if _hf_name else []))
        _log(emit, 4, f"Loading NER models: {_all_names}…")

        if _utils._preextractor is None:
            from src.preextraction.preextractor import Preextractor
            _utils._preextractor = Preextractor()
        preextractor = _utils._preextractor

        _log(emit, 4, "Models loaded — running NER ensemble on chunks…")
        tagged_chunks = preextractor.process_batch(chunks)
        all_ents      = [e for c in tagged_chunks for e in c.get("entities", [])]
        negated       = [e for e in all_ents if e.get("negated")]

        for i, c in enumerate(tagged_chunks, 1):
            ents   = c.get("entities", [])
            neg    = [e for e in ents if e.get("negated")]
            sample = ", ".join(f"{e['text']} ({e['label']})" for e in ents[:4])
            _log(emit, 4, f"  Chunk {i} [{c.get('section', '?')}]: {len(ents)} entities — {sample}{'…' if len(ents) > 4 else ''}")
            if neg:
                _log(emit, 4, f"    ✗ Negated: {', '.join(e['text'] for e in neg)}")

        doi  = next((c.get("doi") for c in tagged_chunks if c.get("doi")), None)
        if doi: _log(emit, 4, f"  DOI extracted: {doi}")
        accs = [a for c in tagged_chunks for a in c.get("accession_numbers", [])]
        if accs: _log(emit, 4, f"  Accessions: {', '.join(a['accession'] for a in accs[:5])}")

        _emit(emit, 4, "done", f"{len(all_ents)} entities tagged", {
            "entity_count":  len(all_ents),
            "negated_count": len(negated),
            "entity_types":  list({e["label"] for e in all_ents}),
            "entities":      all_ents[:40],
        })
        type_counts  = {}
        for e in all_ents:
            type_counts[e["label"]] = type_counts.get(e["label"], 0) + 1
        type_summary = ", ".join(f"{v} {k}" for k, v in sorted(type_counts.items(), key=lambda x: -x[1])[:5])
        _post(emit, 4, [
            f"{len(all_ents)} entities tagged across {len(tagged_chunks)} chunks",
            f"Entity types: {type_summary}",
            f"{len(negated)} negated entities flagged (negated=True)",
            f"DOI: {next((c.get('doi') for c in tagged_chunks if c.get('doi')), 'not found')}",
        ])
        try:
            import json as _jj
            _ckpt_dir = Path(f"data/checkpoints/{_safe_id}")
            _ckpt_dir.mkdir(parents=True, exist_ok=True)
            (_ckpt_dir / "layer4_annotated.json").write_text(
                _jj.dumps(tagged_chunks, default=str), encoding="utf-8"
            )
        except Exception:
            pass
        _ckpt(doc_id, 4)
        return tagged_chunks
    except Exception as e:
        _emit(emit, 4, "error", str(e))
        return None
