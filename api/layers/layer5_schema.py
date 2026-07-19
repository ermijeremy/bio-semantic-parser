"""Layer 5 — Load taxonomy schema (RelationType + EntityType enums)."""
from api.pipeline_utils import _emit, _log, _pre, _post, _ckpt


def run_layer5(emit, doc_id, tagged_chunks, _completed_layers):
    """Load bio-relation schema and return True on success, None on error."""
    def _skip(layer): return layer in _completed_layers

    if _skip(5):
        _pre(emit, 5)
        _emit(emit, 5, "done", "Checkpoint — layer already complete ✓", {})
    else:
        _pre(emit, 5)
    _emit(emit, 5, "running", "Loading taxonomy schema…")
    try:
        from src.schema.taxonomy import RelationType, EntityType
        _log(emit, 5, f"RelationType enum: {len(RelationType)} types in 22 categories")
        _log(emit, 5, f"EntityType enum: {len(EntityType)} types")
        _log(emit, 5, "Sources: BioNLP · Hetionet v1.0 · OpenBioLink · BioCypher primer · Biolink Model v4.4.2")
        _log(emit, 5, "Longevity extensions: extends_lifespan, reduces_lifespan, extends_healthspan, reduces_healthspan, reprograms")
        _emit(emit, 5, "done", "Schema ready", {
            "relation_types": len(RelationType),
            "entity_types":   len(EntityType),
        })
        try:
            from api.rich_stream import capture_demo_output
            from tests.demo_pipeline import show_layer5
            capture_demo_output(show_layer5, tagged_chunks, emit=emit, layer=5)
        except Exception:
            pass
        _post(emit, 5, [
            f"{len(RelationType)} relation types · {len(EntityType)} entity types loaded",
            "Sources: BioNLP · Hetionet · OpenBioLink · BioCypher · Biolink Model v4.4.2",
            "Longevity extensions: extends_lifespan · reduces_lifespan · reprograms · healthspan",
            "Pydantic model ready — 13-field validation enforced on every extraction",
        ])
        _ckpt(doc_id, 5)
        return True
    except Exception as e:
        _emit(emit, 5, "error", str(e))
        return None
