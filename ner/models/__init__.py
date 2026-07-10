"""Model registry.

Metadata is declared statically here so the app can list models without
importing torch/gliner/spacy. The heavy module is imported only when a model is
actually loaded via ``load_model(key)``.
"""
from __future__ import annotations

import importlib

# key -> (module suffix, name, description, extras, prefers_gpu)
# Ordering roughly reflects breadth of coverage / expected benchmark rank.
REGISTRY = {
    "gliner_biomed_large": {
        "module": "gliner_biomed_large",
        "name": "GLiNER-BioMed Large",
        "model_id": "Ihor/gliner-biomed-large-v1.0",
        "description": "Zero-shot GLiNER cross-encoder. Broadest schema coverage (~95%), top F1.",
        "extras": ["gliner", "torch"], "prefers_gpu": True, "family": "GLiNER (zero-shot)",
    },
    "gliner_biomed_base": {
        "module": "gliner_biomed_base",
        "name": "GLiNER-BioMed Base",
        "model_id": "Ihor/gliner-biomed-base-v1.0",
        "description": "Smaller GLiNER cross-encoder. Lower latency/memory than Large.",
        "extras": ["gliner", "torch"], "prefers_gpu": False, "family": "GLiNER (zero-shot)",
    },
    "gliner_biomed_bi_large": {
        "module": "gliner_biomed_bi_large",
        "name": "GLiNER-BioMed Bi-Large",
        "model_id": "Ihor/gliner-biomed-bi-large-v1.0",
        "description": "Bi-encoder GLiNER, scales to many labels. Pin gliner version if 'token_lengths' errors.",
        "extras": ["gliner", "torch"], "prefers_gpu": True, "family": "GLiNER (zero-shot)",
    },
    "scispacy_ensemble": {
        "module": "scispacy_ensemble",
        "name": "scispaCy Ensemble",
        "model_id": "en_ner_bc5cdr_md + jnlpba + bionlp13cg",
        "description": "Three scispaCy pipelines merged. Fast CPU baseline (current pipeline default).",
        "extras": ["scispacy", "spacy"], "prefers_gpu": False, "family": "scispaCy",
    },
    "biomedical_ner_all": {
        "module": "biomedical_ner_all",
        "name": "d4data biomedical-ner-all",
        "model_id": "d4data/biomedical-ner-all",
        "description": "DistilBERT, 41 clinical entity types (MACCROBAT). [researched]",
        "extras": ["transformers", "torch"], "prefers_gpu": False, "family": "Transformer (fixed)",
    },
    "stanza_bionlp13cg": {
        "module": "stanza_bionlp13cg",
        "name": "Stanza BioNLP13CG",
        "model_id": "stanza:en/bionlp13cg",
        "description": "Stanford Stanza CharLM+BiLSTM+CRF, 16 types. Non-transformer baseline. [researched]",
        "extras": ["stanza"], "prefers_gpu": False, "family": "Stanza",
    },
    "hunflair2": {
        "module": "hunflair2",
        "name": "HunFlair2",
        "model_id": "hunflair/hunflair2-ner",
        "description": "Flair cross-corpus tagger. High precision but ~1.2s/sentence (offline use).",
        "extras": ["flair", "scispacy", "torch"], "prefers_gpu": True, "family": "Flair",
    },
    "bent_gene": {
        "module": "bent_gene",
        "name": "BENT-PubMedBERT Gene",
        "model_id": "pruas/BENT-PubMedBERT-NER-Gene",
        "description": "PubMedBERT gene/protein specialist. High precision, low recall on long prose.",
        "extras": ["transformers", "torch"], "prefers_gpu": False, "family": "Transformer (fixed)",
    },
    "bent_disease": {
        "module": "bent_disease",
        "name": "BENT-PubMedBERT Disease",
        "model_id": "pruas/BENT-PubMedBERT-NER-Disease",
        "description": "PubMedBERT disease specialist. Very high precision, low recall.",
        "extras": ["transformers", "torch"], "prefers_gpu": False, "family": "Transformer (fixed)",
    },
    "pubmedbert_protein_structure": {
        "module": "pubmedbert_protein_structure",
        "name": "PubMedBERT ProteinStructure",
        "model_id": "PDBEurope/BiomedNLP-PubMedBERT-ProteinStructure-NER-v3.1",
        "description": "PubMedBERT for protein-structure entities (residue/site/domain/complex).",
        "extras": ["transformers", "torch"], "prefers_gpu": False, "family": "Transformer (fixed)",
    },
    "biobert_diseases": {
        "module": "biobert_diseases",
        "name": "BioBERT Diseases",
        "model_id": "alvaroalon2/biobert_diseases_ner",
        "description": "BioBERT disease baseline (NCBI-Disease/BC5CDR). [researched]",
        "extras": ["transformers", "torch"], "prefers_gpu": False, "family": "BioBERT (fixed)",
    },
    "biobert_chemical": {
        "module": "biobert_chemical",
        "name": "BioBERT Chemical",
        "model_id": "alvaroalon2/biobert_chemical_ner",
        "description": "BioBERT chemical baseline (BC4CHEMD/BC5CDR). [researched]",
        "extras": ["transformers", "torch"], "prefers_gpu": False, "family": "BioBERT (fixed)",
    },
    "biobert_genetic": {
        "module": "biobert_genetic",
        "name": "BioBERT Genetic",
        "model_id": "alvaroalon2/biobert_genetic_ner",
        "description": "BioBERT gene/protein baseline (JNLPBA/BC2GM). [researched]",
        "extras": ["transformers", "torch"], "prefers_gpu": False, "family": "BioBERT (fixed)",
    },
}


def list_models() -> list[dict]:
    """Lightweight metadata for every registered model (no heavy imports)."""
    return [{"key": k, **{kk: vv for kk, vv in v.items() if kk != "module"}}
            for k, v in REGISTRY.items()]


def load_model(key: str):
    """Import the model's module and return its singleton instance (lazy)."""
    if key not in REGISTRY:
        raise KeyError(f"Unknown model key: {key}")
    module = importlib.import_module(f"{__name__}.{REGISTRY[key]['module']}")
    return module.get_model()
