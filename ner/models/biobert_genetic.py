"""BioBERT Genetic NER — alvaroalon2/biobert_genetic_ner.

Researched addition. BioBERT fine-tuned on gene/protein corpora (JNLPBA/BC2GM).
Maps gene/protein spans to GENE.
"""
from __future__ import annotations

from ._hf_pipeline import HFTokenClassificationModel


class Model(HFTokenClassificationModel):
    key = "biobert_genetic"
    name = "BioBERT Genetic"
    model_id = "alvaroalon2/biobert_genetic_ner"
    description = "BioBERT fine-tuned on gene/protein corpora (JNLPBA/BC2GM). Gene/protein -> GENE."
    license = "Apache-2.0"
    homepage = "https://huggingface.co/alvaroalon2/biobert_genetic_ner"
    extras = ("transformers", "torch")
    prefers_gpu = False

    LABEL_MAP = {"GENETIC": "GENE", "GENE": "GENE", "PROTEIN": "GENE"}
    DEFAULT_LABEL = "GENE"

    def _map_label(self, group: str) -> str:
        return "GENE"


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
