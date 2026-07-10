"""Entity schema, NER-detectability tiers, and GLiNER label mappings.

Lifted from src/models_experiment/ner_comparison.ipynb so the standalone
harness carries the same 39-type BioCypher schema and the same natural-language
label set used to drive the zero-shot GLiNER models.
"""
from __future__ import annotations

from enum import Enum


class EntityType(str, Enum):
    # Coding / sequence elements
    GENE = "GENE"
    PROTEIN = "PROTEIN"
    TRANSCRIPT = "TRANSCRIPT"
    EXON = "EXON"
    NON_CODING_RNA = "NON_CODING_RNA"
    # Genomic variation
    GENOMIC_VARIANT = "GENOMIC_VARIANT"
    SEQUENCE_VARIANT = "SEQUENCE_VARIANT"
    STRUCTURAL_VARIANT = "STRUCTURAL_VARIANT"
    # Regulatory & epigenomic
    REGULATORY_REGION = "REGULATORY_REGION"
    ENHANCER = "ENHANCER"
    SUPER_ENHANCER = "SUPER_ENHANCER"
    PROMOTER = "PROMOTER"
    TRANSCRIPTION_FACTOR_BINDING_SITE = "TRANSCRIPTION_FACTOR_BINDING_SITE"
    EPIGENOMIC_FEATURE = "EPIGENOMIC_FEATURE"
    MOTIF = "MOTIF"
    TAD = "TAD"
    # Chemistry & molecules
    SMALL_MOLECULE = "SMALL_MOLECULE"
    MOLECULAR_INTERACTION = "MOLECULAR_INTERACTION"
    MACROMOLECULAR_COMPLEX = "MACROMOLECULAR_COMPLEX"
    # Genetic composition
    HAPLOTYPE = "HAPLOTYPE"
    GENOTYPE = "GENOTYPE"
    # Disease & phenotype
    DISEASE = "DISEASE"
    CANCER = "CANCER"
    PHENOTYPE = "PHENOTYPE"
    SYMPTOM = "SYMPTOM"
    # Biological processes & functions
    PATHWAY = "PATHWAY"
    REACTION = "REACTION"
    BIOLOGICAL_PROCESS = "BIOLOGICAL_PROCESS"
    MOLECULAR_FUNCTION = "MOLECULAR_FUNCTION"
    CELLULAR_COMPONENT = "CELLULAR_COMPONENT"
    # Anatomy & cell biology
    ANATOMY = "ANATOMY"
    TISSUE = "TISSUE"
    CELL_TYPE = "CELL_TYPE"
    CELL_LINE = "CELL_LINE"
    DEVELOPMENTAL_STAGE = "DEVELOPMENTAL_STAGE"
    # Experimental context
    EXPERIMENTAL_FACTOR = "EXPERIMENTAL_FACTOR"
    THREE_D_GENOME_STRUCTURE = "THREE_D_GENOME_STRUCTURE"
    # Taxonomy
    ORGANISM = "ORGANISM"
    # Catch-all
    OTHER = "OTHER"


ALL_TYPES = [e.value for e in EntityType]

# NLP detectability tiers — how reliably surface NER can find each type in prose.
TIER_1_NLP_DETECTABLE = {
    "GENE", "PROTEIN", "NON_CODING_RNA", "GENOMIC_VARIANT", "SEQUENCE_VARIANT",
    "SMALL_MOLECULE", "MACROMOLECULAR_COMPLEX", "DISEASE", "CANCER", "PHENOTYPE",
    "SYMPTOM", "PATHWAY", "BIOLOGICAL_PROCESS", "MOLECULAR_FUNCTION",
    "CELLULAR_COMPONENT", "ANATOMY", "TISSUE", "CELL_TYPE", "CELL_LINE", "ORGANISM",
}

TIER_2_NLP_MODERATE = {
    "TRANSCRIPT", "REGULATORY_REGION", "ENHANCER", "PROMOTER",
    "TRANSCRIPTION_FACTOR_BINDING_SITE", "EPIGENOMIC_FEATURE",
    "MOLECULAR_INTERACTION", "HAPLOTYPE", "REACTION",
    "DEVELOPMENTAL_STAGE", "EXPERIMENTAL_FACTOR",
}

TIER_3_NLP_HARD = {
    "EXON", "SUPER_ENHANCER", "MOTIF", "TAD", "STRUCTURAL_VARIANT",
    "GENOTYPE", "THREE_D_GENOME_STRUCTURE", "OTHER",
}


def tier_of(entity_type: str) -> str:
    t = entity_type.upper()
    if t in TIER_1_NLP_DETECTABLE:
        return "T1"
    if t in TIER_2_NLP_MODERATE:
        return "T2"
    return "T3"


# ── GLiNER zero-shot labels ──────────────────────────────────────────────────
# Natural-language label per schema type, and the reverse map back to the enum.
GLINER_LABELS = [
    "gene", "protein", "RNA transcript or mRNA isoform", "exon",
    "non-coding RNA such as miRNA lncRNA or circRNA",
    "genomic variant or SNP", "sequence variant or point mutation",
    "structural variant such as CNV deletion or translocation",
    "regulatory region", "enhancer element", "super-enhancer",
    "gene promoter", "transcription factor binding site",
    "epigenomic feature such as histone mark or methylation",
    "sequence motif or transcription factor motif",
    "topologically associating domain TAD",
    "small molecule drug or metabolite",
    "molecular interaction or protein-protein interaction",
    "macromolecular complex",
    "haplotype", "genotype",
    "disease", "cancer or tumour type",
    "phenotype", "clinical symptom",
    "biological pathway",
    "biochemical reaction",
    "biological process",
    "molecular function",
    "cellular component or organelle",
    "anatomical structure",
    "tissue type",
    "cell type",
    "cell line",
    "developmental stage or life stage",
    "experimental condition or treatment",
    "3D genome structure or chromatin loop",
    "organism or species",
]

GLINER_MAP = {
    "gene": "GENE",
    "protein": "PROTEIN",
    "RNA transcript or mRNA isoform": "TRANSCRIPT",
    "exon": "EXON",
    "non-coding RNA such as miRNA lncRNA or circRNA": "NON_CODING_RNA",
    "genomic variant or SNP": "GENOMIC_VARIANT",
    "sequence variant or point mutation": "SEQUENCE_VARIANT",
    "structural variant such as CNV deletion or translocation": "STRUCTURAL_VARIANT",
    "regulatory region": "REGULATORY_REGION",
    "enhancer element": "ENHANCER",
    "super-enhancer": "SUPER_ENHANCER",
    "gene promoter": "PROMOTER",
    "transcription factor binding site": "TRANSCRIPTION_FACTOR_BINDING_SITE",
    "epigenomic feature such as histone mark or methylation": "EPIGENOMIC_FEATURE",
    "sequence motif or transcription factor motif": "MOTIF",
    "topologically associating domain TAD": "TAD",
    "small molecule drug or metabolite": "SMALL_MOLECULE",
    "molecular interaction or protein-protein interaction": "MOLECULAR_INTERACTION",
    "macromolecular complex": "MACROMOLECULAR_COMPLEX",
    "haplotype": "HAPLOTYPE",
    "genotype": "GENOTYPE",
    "disease": "DISEASE",
    "cancer or tumour type": "CANCER",
    "phenotype": "PHENOTYPE",
    "clinical symptom": "SYMPTOM",
    "biological pathway": "PATHWAY",
    "biochemical reaction": "REACTION",
    "biological process": "BIOLOGICAL_PROCESS",
    "molecular function": "MOLECULAR_FUNCTION",
    "cellular component or organelle": "CELLULAR_COMPONENT",
    "anatomical structure": "ANATOMY",
    "tissue type": "TISSUE",
    "cell type": "CELL_TYPE",
    "cell line": "CELL_LINE",
    "developmental stage or life stage": "DEVELOPMENTAL_STAGE",
    "experimental condition or treatment": "EXPERIMENTAL_FACTOR",
    "3D genome structure or chromatin loop": "THREE_D_GENOME_STRUCTURE",
    "organism or species": "ORGANISM",
}
