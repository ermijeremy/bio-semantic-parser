"""GLiNER-BioMed Bi-Large (bi-encoder) — Ihor/gliner-biomed-bi-large-v1.0.

Bi-encoder variant: label and text encoded separately, so it scales to large
label sets and is typically faster than the cross-encoder. Note: the notebook
run hit a gliner/transformers version mismatch ('token_lengths' kwarg) that
zeroed its score — pin a compatible gliner build if you see that error.
"""
from __future__ import annotations

from . import _cache  # noqa: F401
from ..base import BaseNERModel, Entity
from ..schema import GLINER_LABELS, GLINER_MAP

_THRESHOLD = 0.5


class Model(BaseNERModel):
    key = "gliner_biomed_bi_large"
    name = "GLiNER-BioMed Bi-Large"
    model_id = "Ihor/gliner-biomed-bi-large-v1.0"
    description = "Bi-encoder GLiNER: separate label/text encoders, scales to many labels. Faster at scale."
    license = "Apache-2.0"
    homepage = "https://huggingface.co/Ihor/gliner-biomed-bi-large-v1.0"
    extras = ("gliner", "torch")
    prefers_gpu = True

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
