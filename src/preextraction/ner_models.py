"""
Layer 4 — Self-contained NER model definitions

Everything the Preextractor ensemble needs: the Entity span dataclass, the
scispaCy label→schema map, and the two lazily-loaded models
(GLiNER-BioMed Base, Stanza BioNLP13CG).

GLiNER zero-shot labels and the label→schema map live in taxonomy.py
(single source of truth).

Heavy checkpoints load on first predict so importing this module stays cheap.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from src.schema.taxonomy import GLINER_LABELS, GLINER_MAP

_log = logging.getLogger(__name__)


@dataclass
class Entity:
    """A single predicted span. Offsets are character-level, end-exclusive."""
    start: int
    end: int
    text: str
    label: str
    score: float = 1.0
    source: str = ""
    source_model: str = ""

    def as_tuple(self) -> tuple:
        return (self.start, self.end, self.text, self.label)


class _BaseNERModel:
    """Minimal lazy-loading base: load() on first predict, then _predict()."""
    model_id: str = ""

    def __init__(self) -> None:
        self._loaded = False

    def load(self) -> None:
        raise NotImplementedError

    def _predict(self, text: str) -> list[Entity]:
        raise NotImplementedError

    def ensure_loaded(self) -> None:
        if not self._loaded:
            try:
                self.load()
                self._loaded = True
                _log.info("[NER] loaded %s", self.model_id or type(self).__name__)
            except Exception:
                _log.exception("[NER] FAILED to load %s — will be skipped", self.model_id or type(self).__name__)
                raise

    def predict(self, text: str) -> list[Entity]:
        self.ensure_loaded()
        return self._predict(text)


# ── scispaCy raw-label → BioCypher schema type ────────────────────────────────
SCISPACY_MAP = {
    "DISEASE": "DISEASE", "CHEMICAL": "SMALL_MOLECULE",
    "SIMPLE_CHEMICAL": "SMALL_MOLECULE",
    "DNA": "NON_CODING_RNA", "RNA": "NON_CODING_RNA",
    "PROTEIN": "PROTEIN", "CELL_TYPE": "CELL_TYPE", "CELL_LINE": "CELL_LINE",
    "GENE_OR_GENE_PRODUCT": "GENE", "CANCER": "CANCER",
    "ORGANISM": "ORGANISM", "TISSUE": "TISSUE",
    "CELLULAR_COMPONENT": "CELLULAR_COMPONENT",
    "ORGAN": "ANATOMY", "MULTI-TISSUE_STRUCTURE": "ANATOMY",
}


# ── GLiNER zero-shot labels + reverse map to schema types ─────────────────────
_GLINER_MAX_TOKENS = 1800  # safe margin below 2048 hard limit


def _split_sentences(text: str) -> list[tuple[str, int]]:
    """Split text into (sentence, char_offset) pairs."""
    import re
    parts = re.split(r'(?<=[.!?])\s+', text)
    result = []
    offset = 0
    for part in parts:
        result.append((part, offset))
        offset += len(part) + 1  # +1 for the space
    return result


class _GLiNERBaseModel(_BaseNERModel):
    _THRESHOLD = 0.5

    def load(self) -> None:
        import torch
        from gliner import GLiNER
        self._model = GLiNER.from_pretrained(self.model_id)
        if torch.cuda.is_available():
            self._model = self._model.to("cuda")

    def _predict(self, text: str) -> list[Entity]:
        # Estimate token count (~4 chars/token) and chunk if too long
        if len(text) <= _GLINER_MAX_TOKENS * 4:
            return self._predict_chunk(text, 0)

        sentences = _split_sentences(text)
        all_ents: list[Entity] = []
        chunk, chunk_offset = "", 0
        for sent, sent_offset in sentences:
            if not chunk:
                chunk_offset = sent_offset
            candidate = (chunk + " " + sent).strip() if chunk else sent
            if len(candidate) > _GLINER_MAX_TOKENS * 4 and chunk:
                all_ents.extend(self._predict_chunk(chunk, chunk_offset))
                chunk, chunk_offset = sent, sent_offset
            else:
                chunk = candidate
        if chunk:
            all_ents.extend(self._predict_chunk(chunk, chunk_offset))
        return all_ents

    def _predict_chunk(self, text: str, char_offset: int) -> list[Entity]:
        ents = self._model.predict_entities(
            text, GLINER_LABELS, threshold=self._THRESHOLD, flat_ner=True
        )
        return [
            Entity(e["start"] + char_offset, e["end"] + char_offset, e["text"],
                   GLINER_MAP.get(e["label"], "OTHER"), e.get("score", 1.0),
                   source=self.model_id.split("/")[-1], source_model=self.model_id)
            for e in ents
        ]


class _GLiNERLarge(_GLiNERBaseModel):
    model_id = "Ihor/gliner-biomed-large-v1.0"

# ── singleton accessors ───────────────────────────────────────────────────────
_GLINER_LARGE = None
_singleton_lock = threading.Lock()


def get_gliner_large() -> _GLiNERLarge:
    global _GLINER_LARGE
    if _GLINER_LARGE is None:
        with _singleton_lock:
            if _GLINER_LARGE is None:
                _GLINER_LARGE = _GLiNERLarge()
    return _GLINER_LARGE
