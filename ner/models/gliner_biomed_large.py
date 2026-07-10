"""GLiNER-BioMed Large (cross-encoder) — Ihor/gliner-biomed-large-v1.0.

Zero-shot biomedical NER driven by natural-language type labels. Top performer
in the notebook benchmark (partial F1 ~0.88, ~95% schema coverage).
"""
from __future__ import annotations

from ..base import BaseNERModel, Entity
from ..schema import GLINER_LABELS, GLINER_MAP

_THRESHOLD = 0.5


class Model(BaseNERModel):
    key = "gliner_biomed_large"
    name = "GLiNER-BioMed Large"
    model_id = "Ihor/gliner-biomed-large-v1.0"
    description = "Zero-shot GLiNER cross-encoder distilled from biomedical LLMs. Broadest schema coverage."
    license = "Apache-2.0"
    homepage = "https://huggingface.co/Ihor/gliner-biomed-large-v1.0"
    extras = ("gliner", "torch")
    prefers_gpu = True

    def load(self) -> None:
        import torch
        from gliner import GLiNER
        self._model = GLiNER.from_pretrained(self.model_id)
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
