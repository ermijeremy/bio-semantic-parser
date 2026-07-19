"""
Layer 4 — Self-contained NER model definitions

Everything the Preextractor ensemble needs, with no dependency on any external
NER research package: the Entity span dataclass, the scispaCy label→schema map,
the GLiNER zero-shot label set + reverse map, and the three lazily-loaded models
(GLiNER-BioMed Large/Base, Stanza BioNLP13CG).

Heavy checkpoints load on first predict so importing this module stays cheap.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Entity:
    """A single predicted span. Offsets are character-level, end-exclusive."""
    start: int
    end: int
    text: str
    label: str
    score: float = 1.0

    def as_tuple(self) -> tuple:
        return (self.start, self.end, self.text, self.label)


class _BaseNERModel:
    """Minimal lazy-loading base: load() on first predict, then _predict()."""
    model_id: str = ""

    def __init__(self) -> None:
        self._loaded = False

    def load(self) -> None:
        raise NotImplementedError

    def _predict(self, text: str) -> list[Entity]:
        raise NotImplementedError

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()
            self._loaded = True

    def predict(self, text: str) -> list[Entity]:
        self.ensure_loaded()
        return self._predict(text)


# ── scispaCy raw-label → BioCypher schema type ────────────────────────────────
SCISPACY_MAP = {
    "DISEASE": "DISEASE", "CHEMICAL": "SMALL_MOLECULE",
    "SIMPLE_CHEMICAL": "SMALL_MOLECULE",
    "DNA": "NON_CODING_RNA", "RNA": "NON_CODING_RNA",
    "PROTEIN": "PROTEIN", "CELL_TYPE": "CELL_TYPE", "CELL_LINE": "CELL_LINE",
    "GENE_OR_GENE_PRODUCT": "GENE", "CANCER": "CANCER",
    "ORGANISM": "ORGANISM", "TISSUE": "TISSUE",
    "CELLULAR_COMPONENT": "CELLULAR_COMPONENT",
    "ORGAN": "ANATOMY", "MULTI-TISSUE_STRUCTURE": "ANATOMY",
}


# ── GLiNER zero-shot labels + reverse map to schema types ─────────────────────
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


# ── GLiNER-BioMed Large (cross-encoder) ───────────────────────────────────────
class _GLiNERLarge(_BaseNERModel):
    model_id = "Ihor/gliner-biomed-large-v1.0"
    _THRESHOLD = 0.5

    def load(self) -> None:
        import torch
        from gliner import GLiNER
        self._model = GLiNER.from_pretrained(self.model_id)
        if torch.cuda.is_available():
            self._model = self._model.to("cuda")

    def _predict(self, text: str) -> list[Entity]:
        ents = self._model.predict_entities(
            text, GLINER_LABELS, threshold=self._THRESHOLD, flat_ner=True
        )
        return [
            Entity(e["start"], e["end"], e["text"],
                   GLINER_MAP.get(e["label"], "OTHER"), e.get("score", 1.0))
            for e in ents
        ]


# ── GLiNER-BioMed Base (smaller/faster cross-encoder) ─────────────────────────
class _GLiNERBase(_BaseNERModel):
    model_id = "Ihor/gliner-biomed-base-v1.0"
    _THRESHOLD = 0.5

    def load(self) -> None:
        import torch
        from gliner import GLiNER
        self._model = GLiNER.from_pretrained(self.model_id)
        if torch.cuda.is_available():
            self._model = self._model.to("cuda")

    def _predict(self, text: str) -> list[Entity]:
        ents = self._model.predict_entities(
            text, GLINER_LABELS, threshold=self._THRESHOLD, flat_ner=True
        )
        return [
            Entity(e["start"], e["end"], e["text"],
                   GLINER_MAP.get(e["label"], "OTHER"), e.get("score", 1.0))
            for e in ents
        ]


# ── Stanza BioNLP13CG (CharLM + BiLSTM + CRF) ─────────────────────────────────
_STANZA_MAP = {
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


class _StanzaBioNLP13CG(_BaseNERModel):
    model_id = "stanza:en/bionlp13cg"

    def load(self) -> None:
        import stanza
        # Download is idempotent; only fetches the package the first time.
        stanza.download("en", package="bionlp13cg",
                        processors={"tokenize": "craft", "ner": "bionlp13cg"}, verbose=False)
        self._nlp = stanza.Pipeline(
            "en", package="bionlp13cg",
            processors={"tokenize": "craft", "ner": "bionlp13cg"}, verbose=False,
        )

    def _predict(self, text: str) -> list[Entity]:
        doc = self._nlp(text)
        out = []
        for ent in doc.ents:
            label = _STANZA_MAP.get(ent.type.upper(), ent.type.upper())
            out.append(Entity(ent.start_char, ent.end_char, ent.text, label))
        return out


# ── singleton accessors ───────────────────────────────────────────────────────
_GLINER_LARGE = None
_GLINER_BASE = None
_STANZA = None


def get_gliner_large() -> _GLiNERLarge:
    global _GLINER_LARGE
    if _GLINER_LARGE is None:
        _GLINER_LARGE = _GLiNERLarge()
    return _GLINER_LARGE


def get_gliner_base() -> _GLiNERBase:
    global _GLINER_BASE
    if _GLINER_BASE is None:
        _GLINER_BASE = _GLiNERBase()
    return _GLINER_BASE


def get_stanza() -> _StanzaBioNLP13CG:
    global _STANZA
    if _STANZA is None:
        _STANZA = _StanzaBioNLP13CG()
    return _STANZA
