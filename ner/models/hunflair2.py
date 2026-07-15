"""HunFlair2 — hunflair/hunflair2-ner (Flair).

Cross-corpus SOTA for gene/disease/chemical/species/cell-line, but heavy: the
notebook measured ~1.2s/sentence, so treat it as an offline re-annotation pass
rather than an inline component.
"""
from __future__ import annotations

from . import _cache  # noqa: F401 — sets FLAIR_CACHE_ROOT before flair import
from ..base import BaseNERModel, Entity

HF2_MAP = {
    "GENE": "GENE", "DISEASE": "DISEASE",
    "CHEMICAL": "SMALL_MOLECULE", "SPECIES": "ORGANISM", "CELL_LINE": "CELL_LINE",
}


class Model(BaseNERModel):
    key = "hunflair2"
    name = "HunFlair2"
    model_id = "hunflair/hunflair2-ner"
    description = "Flair-based cross-corpus tagger (gene/disease/chemical/species/cell line). High precision, slow."
    license = "MIT"
    homepage = "https://huggingface.co/hunflair/hunflair2-ner"
    extras = ("flair", "scispacy", "torch")
    prefers_gpu = True

    def load(self) -> None:
        import flair
        # Point Flair's cache at our local directory.
        flair.cache_root = _cache.CACHE_DIR / "flair"
        from flair.models.prefixed_tagger import PrefixedSequenceTagger
        self._tagger = PrefixedSequenceTagger.load(self.model_id)

    def _predict(self, text: str) -> list[Entity]:
        from flair.data import Sentence
        from flair.tokenization import SciSpacyTokenizer
        sentence = Sentence(text, use_tokenizer=SciSpacyTokenizer())
        self._tagger.predict(sentence)
        return [
            Entity(span.start_position, span.end_position, span.text,
                   HF2_MAP.get(span.tag.upper(), span.tag.upper()), span.score)
            for span in sentence.get_spans("ner")
        ]


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
