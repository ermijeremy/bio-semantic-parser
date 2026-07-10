"""BioBERT Chemical NER — alvaroalon2/biobert_chemical_ner.

Researched addition. BioBERT fine-tuned on chemical corpora (BC4CHEMD/BC5CDR).
Maps chemical spans to SMALL_MOLECULE.
"""
from __future__ import annotations

from ._hf_pipeline import HFTokenClassificationModel


class Model(HFTokenClassificationModel):
    key = "biobert_chemical"
    name = "BioBERT Chemical"
    model_id = "alvaroalon2/biobert_chemical_ner"
    description = "BioBERT fine-tuned on chemical corpora (BC4CHEMD/BC5CDR). Chemicals -> SMALL_MOLECULE."
    license = "Apache-2.0"
    homepage = "https://huggingface.co/alvaroalon2/biobert_chemical_ner"
    extras = ("transformers", "torch")
    prefers_gpu = False

    LABEL_MAP = {"CHEMICAL": "SMALL_MOLECULE"}
    DEFAULT_LABEL = "SMALL_MOLECULE"

    def _map_label(self, group: str) -> str:
        return "SMALL_MOLECULE"


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
