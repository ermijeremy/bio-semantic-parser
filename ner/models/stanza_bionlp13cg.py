"""Stanza BioNLP13CG NER — Stanford Stanza biomedical package.

Researched addition. Different architecture from the transformer models here:
character-LM + BiLSTM + CRF. The BioNLP13CG package covers 16 entity types
(genes, chemicals, cancer, cell, anatomy, organism, ...), giving a non-BERT
point of comparison.
"""
from __future__ import annotations

from ..base import BaseNERModel, Entity

# BioNLP13CG NER labels -> BioCypher schema.
_MAP = {
    "GENE_OR_GENE_PRODUCT": "GENE",
    "SIMPLE_CHEMICAL": "SMALL_MOLECULE",
    "CANCER": "CANCER",
    "CELL": "CELL_TYPE",
    "CELLULAR_COMPONENT": "CELLULAR_COMPONENT",
    "ORGAN": "ANATOMY",
    "ORGANISM": "ORGANISM",
    "ORGANISM_SUBSTANCE": "SMALL_MOLECULE",
    "ORGANISM_SUBDIVISION": "ANATOMY",
    "TISSUE": "TISSUE",
    "MULTI-TISSUE_STRUCTURE": "ANATOMY",
    "ANATOMICAL_SYSTEM": "ANATOMY",
    "AMINO_ACID": "SMALL_MOLECULE",
    "PATHOLOGICAL_FORMATION": "PHENOTYPE",
    "IMMATERIAL_ANATOMICAL_ENTITY": "ANATOMY",
    "DEVELOPING_ANATOMICAL_STRUCTURE": "DEVELOPMENTAL_STAGE",
}


class Model(BaseNERModel):
    key = "stanza_bionlp13cg"
    name = "Stanza BioNLP13CG"
    model_id = "stanza:en/bionlp13cg"
    description = "Stanford Stanza CharLM+BiLSTM+CRF, 16 BioNLP13CG types. Non-transformer baseline."
    license = "Apache-2.0"
    homepage = "https://stanfordnlp.github.io/stanza/available_biomed_models.html"
    extras = ("stanza",)
    prefers_gpu = False

    def load(self) -> None:
        import stanza
        # Download is idempotent; only fetches the package the first time.
        stanza.download("en", package="bionlp13cg", processors={"tokenize": "craft", "ner": "bionlp13cg"}, verbose=False)
        self._nlp = stanza.Pipeline(
            "en", package="bionlp13cg", processors={"tokenize": "craft", "ner": "bionlp13cg"}, verbose=False,
        )

    def _predict(self, text: str) -> list[Entity]:
        doc = self._nlp(text)
        out = []
        for ent in doc.ents:
            label = _MAP.get(ent.type.upper(), ent.type.upper())
            out.append(Entity(ent.start_char, ent.end_char, ent.text, label))
        return out


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
