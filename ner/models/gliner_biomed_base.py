"""GLiNER-BioMed Base (cross-encoder) — Ihor/gliner-biomed-base-v1.0.

Smaller GLiNER cross-encoder. Lower latency/memory than Large while
retaining broad schema coverage.
"""
from __future__ import annotations

from . import _cache  # noqa: F401
from ..base import BaseNERModel, Entity
from ..schema import GLINER_LABELS, GLINER_MAP

# Lower than GLiNER-Large's 0.5: in the ensemble, Base runs as a secondary
# recovery sweep over regions the larger models left uncovered, so it trades a
# little precision for recall on borderline spans.
_THRESHOLD = 0.40


class Model(BaseNERModel):
    key = "gliner_biomed_base"
    name = "GLiNER-BioMed Base"
    model_id = "Ihor/gliner-biomed-base-v1.0"
    description = "Smaller GLiNER cross-encoder. Lower latency/memory than Large."
    license = "Apache-2.0"
    homepage = "https://huggingface.co/Ihor/gliner-biomed-base-v1.0"
    extras = ("gliner", "torch")
    prefers_gpu = False

    def load(self) -> None:
        import torch
        from gliner import GLiNER
        hub_dir = str(_cache.CACHE_DIR / "hub")
        self._model = GLiNER.from_pretrained(self.model_id, cache_dir=hub_dir)
        if torch.cuda.is_available():
            self._model = self._model.to("cuda")

    def _predict(self, text: str) -> list[Entity]:
        ents = self._model.predict_entities(
            text, GLINER_LABELS, threshold=_THRESHOLD, flat_ner=True
        )
        return [
            Entity(e["start"], e["end"], e["text"],
                   GLINER_MAP.get(e["label"], "OTHER"), e.get("score", 1.0))
            for e in ents
        ]


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
