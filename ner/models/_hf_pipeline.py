"""Shared helper for HuggingFace token-classification NER models.

Keeps each model file to just its id + label map, while the actual pipeline
plumbing (device selection, span extraction) lives here.
"""
from __future__ import annotations

from ..base import BaseNERModel, Entity


class HFTokenClassificationModel(BaseNERModel):
    """Subclasses set model_id and LABEL_MAP; DEFAULT_LABEL is the fallback type."""
    LABEL_MAP: dict = {}
    DEFAULT_LABEL = "OTHER"

    def load(self) -> None:
        from transformers import pipeline as hf_pipeline
        device_id = self._device_id()
        self._pipe = hf_pipeline(
            "token-classification",
            model=self.model_id,
            aggregation_strategy="simple",
            device=device_id,
        )

    @staticmethod
    def _device_id() -> int:
        try:
            import torch
            return 0 if torch.cuda.is_available() else -1
        except Exception:
            return -1

    def _map_label(self, group: str) -> str:
        return self.LABEL_MAP.get(group.upper(), self.DEFAULT_LABEL)

    def _predict(self, text: str) -> list[Entity]:
        out = []
        for r in self._pipe(text):
            out.append(Entity(
                int(r["start"]), int(r["end"]), r["word"],
                self._map_label(r["entity_group"]), float(r.get("score", 1.0)),
            ))
        return out
