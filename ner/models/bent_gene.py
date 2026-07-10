"""BENT PubMedBERT NER — Gene — pruas/BENT-PubMedBERT-NER-Gene.

Single-purpose gene/protein tagger. Notebook finding: very high precision but
low recall on complex prose (narrow training distribution).
"""
from __future__ import annotations

from ._hf_pipeline import HFTokenClassificationModel


class Model(HFTokenClassificationModel):
    key = "bent_gene"
    name = "BENT-PubMedBERT Gene"
    model_id = "pruas/BENT-PubMedBERT-NER-Gene"
    description = "PubMedBERT fine-tuned for gene/protein spans. High precision, low recall on long sentences."
    license = "Apache-2.0"
    homepage = "https://huggingface.co/pruas/BENT-PubMedBERT-NER-Gene"
    extras = ("transformers", "torch")
    prefers_gpu = False

    LABEL_MAP = {"GENE": "GENE", "BIO": "GENE"}
    DEFAULT_LABEL = "PROTEIN"

    def _map_label(self, group: str) -> str:
        return "GENE" if "GENE" in group.upper() else "PROTEIN"


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
