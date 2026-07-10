"""PubMedBERT ProteinStructure NER —
PDBEurope/BiomedNLP-PubMedBERT-ProteinStructure-NER-v3.1.

Specialised for protein structure language: proteins, residues, sites, domains,
complexes. Useful as a residue/SEQUENCE_VARIANT specialist.
"""
from __future__ import annotations

from ._hf_pipeline import HFTokenClassificationModel


class Model(HFTokenClassificationModel):
    key = "pubmedbert_protein_structure"
    name = "PubMedBERT ProteinStructure"
    model_id = "PDBEurope/BiomedNLP-PubMedBERT-ProteinStructure-NER-v3.1"
    description = "PubMedBERT for protein-structure entities (protein/residue/site/domain/complex)."
    license = "MIT"
    homepage = "https://huggingface.co/PDBEurope/BiomedNLP-PubMedBERT-ProteinStructure-NER-v3.1"
    extras = ("transformers", "torch")
    prefers_gpu = False

    LABEL_MAP = {
        "PROTEIN": "PROTEIN", "RESIDUE": "SEQUENCE_VARIANT",
        "SITE": "MOLECULAR_FUNCTION", "DOMAIN": "PROTEIN",
        "COMPLEX": "MACROMOLECULAR_COMPLEX",
    }
    DEFAULT_LABEL = "PROTEIN"


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
