"""d4data/biomedical-ner-all — DistilBERT, 41 clinical entity types.

Researched addition. Trained on the MACCROBAT case-report corpus; broadest
label set of the fixed-taxonomy models here (diseases, signs/symptoms,
medications, procedures, anatomy, demographics). Good clinical-prose coverage,
but its label space only partially overlaps the BioCypher schema.
"""
from __future__ import annotations

from ._hf_pipeline import HFTokenClassificationModel

# MACCROBAT labels -> BioCypher schema. Unmapped clinical labels fall to OTHER.
_MAP = {
    "DISEASE_DISORDER": "DISEASE",
    "SIGN_SYMPTOM": "SYMPTOM",
    "BIOLOGICAL_STRUCTURE": "ANATOMY",
    "MEDICATION": "SMALL_MOLECULE",
    "DETAILED_DESCRIPTION": "OTHER",
    "THERAPEUTIC_PROCEDURE": "OTHER",
    "DIAGNOSTIC_PROCEDURE": "OTHER",
    "LAB_VALUE": "OTHER",
    "NONBIOLOGICAL_LOCATION": "OTHER",
    "BIOLOGICAL_ATTRIBUTE": "MOLECULAR_FUNCTION",
    "CLINICAL_EVENT": "OTHER",
    "OUTCOME": "PHENOTYPE",
    "DISTANCE": "OTHER", "AREA": "OTHER", "VOLUME": "OTHER", "MASS": "OTHER",
    "SEVERITY": "OTHER",
}


class Model(HFTokenClassificationModel):
    key = "biomedical_ner_all"
    name = "d4data biomedical-ner-all"
    model_id = "d4data/biomedical-ner-all"
    description = "DistilBERT tagging 41 clinical entity types (MACCROBAT). Strong on case-report prose."
    license = "Apache-2.0"
    homepage = "https://huggingface.co/d4data/biomedical-ner-all"
    extras = ("transformers", "torch")
    prefers_gpu = False

    LABEL_MAP = _MAP
    DEFAULT_LABEL = "OTHER"


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
