"""BioBERT Diseases NER — alvaroalon2/biobert_diseases_ner.

Researched addition. Classic BioBERT fine-tune (NCBI-Disease / BC5CDR). A
fixed-taxonomy transformer baseline against the zero-shot GLiNER models.
"""
from __future__ import annotations

from ._hf_pipeline import HFTokenClassificationModel


class Model(HFTokenClassificationModel):
    key = "biobert_diseases"
    name = "BioBERT Diseases"
    model_id = "alvaroalon2/biobert_diseases_ner"
    description = "BioBERT fine-tuned on disease corpora (NCBI-Disease/BC5CDR). Fixed-taxonomy baseline."
    license = "Apache-2.0"
    homepage = "https://huggingface.co/alvaroalon2/biobert_diseases_ner"
    extras = ("transformers", "torch")
    prefers_gpu = False

    LABEL_MAP = {"DISEASE": "DISEASE"}
    DEFAULT_LABEL = "DISEASE"

    def _map_label(self, group: str) -> str:
        return "DISEASE"


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
