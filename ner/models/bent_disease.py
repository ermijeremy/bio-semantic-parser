"""BENT PubMedBERT NER — Disease — pruas/BENT-PubMedBERT-NER-Disease.

Single-purpose disease tagger. Same narrow-distribution pattern as the gene
variant: near-perfect precision, poor recall on realistic prose.
"""
from __future__ import annotations

from ._hf_pipeline import HFTokenClassificationModel


class Model(HFTokenClassificationModel):
    key = "bent_disease"
    name = "BENT-PubMedBERT Disease"
    model_id = "pruas/BENT-PubMedBERT-NER-Disease"
    description = "PubMedBERT fine-tuned for disease spans. Very high precision, low recall."
    license = "Apache-2.0"
    homepage = "https://huggingface.co/pruas/BENT-PubMedBERT-NER-Disease"
    extras = ("transformers", "torch")
    prefers_gpu = False

    DEFAULT_LABEL = "DISEASE"

    def _map_label(self, group: str) -> str:
        return "DISEASE"


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
