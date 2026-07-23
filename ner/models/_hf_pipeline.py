"""Shared helper for HuggingFace token-classification NER models.

Keeps each model file to just its id + label map, while the actual pipeline
plumbing (device selection, span extraction) lives here.

Cache note: ``_cache`` is imported first so that HF_HOME / HF_HUB_CACHE
point at  ner/models/_hf_cache/  before any transformers symbols are imported.
Models download once on first use; subsequent loads read from the local cache
with no network round-trip.

Compatibility: works with transformers 4.x (flair co-installs 4.57.x).
The model + tokenizer are loaded separately with an explicit cache_dir so the
pipeline() call never needs one.
"""
from __future__ import annotations

from . import _cache  # noqa: F401 — must be first, sets env-vars before torch
from ..base import BaseNERModel, Entity


class HFTokenClassificationModel(BaseNERModel):
    """Subclasses set model_id and LABEL_MAP; DEFAULT_LABEL is the fallback type."""
    LABEL_MAP: dict = {}
    DEFAULT_LABEL = "OTHER"

    def load(self) -> None:
        from transformers import (
            AutoTokenizer,
            AutoModelForTokenClassification,
            pipeline as hf_pipeline,
        )

        hub_dir = str(_cache.CACHE_DIR / "hub")
        device_id = self._device_id()

        # Load model + tokenizer explicitly with cache_dir so weights are
        # pulled from the local snapshot rather than hitting the network.
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, cache_dir=hub_dir
        )
        model = AutoModelForTokenClassification.from_pretrained(
            self.model_id, cache_dir=hub_dir
        )

        self._pipe = hf_pipeline(
            "token-classification",
            model=model,
            tokenizer=tokenizer,
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
            start, end = int(r["start"]), int(r["end"])
            word = text[start:end] if start >= 0 and end <= len(text) else r["word"]
            out.append(Entity(
                start, end, word,
                self._map_label(r["entity_group"]), float(r.get("score", 1.0)),
            ))
        return out
