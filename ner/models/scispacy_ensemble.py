"""scispaCy 3-model ensemble — BC5CDR + JNLPBA + BioNLP13CG.

Merges entities from three specialised scispaCy pipelines, first-span-wins on
overlap. This mirrors the pipeline's current pre-extraction baseline.
"""
from __future__ import annotations

from ..base import BaseNERModel, Entity

# Raw scispaCy label -> schema type. Covers the full raw-label sets of all three
# pipelines: BC5CDR (DISEASE, CHEMICAL), JNLPBA (DNA, RNA, PROTEIN, CELL_TYPE,
# CELL_LINE), and BioNLP13CG (the 16 broad-bio types). Kept aligned with the
# Stanza BioNLP13CG mapping (ner/models/stanza_bionlp13cg.py) so both taggers map
# identical raw types to identical schema types. Unmapped labels pass through
# uppercased here; the preextractor merge falls them back to OTHER instead.
SCISPACY_MAP = {
    # ── BC5CDR ────────────────────────────────────────────────────────────────
    "DISEASE": "DISEASE",
    "CHEMICAL": "SMALL_MOLECULE",
    # ── JNLPBA ────────────────────────────────────────────────────────────────
    "DNA": "NON_CODING_RNA", "RNA": "NON_CODING_RNA",
    "PROTEIN": "PROTEIN", "CELL_TYPE": "CELL_TYPE", "CELL_LINE": "CELL_LINE",
    # ── BioNLP13CG (16 types) ─────────────────────────────────────────────────
    "GENE_OR_GENE_PRODUCT": "GENE",
    "SIMPLE_CHEMICAL": "SMALL_MOLECULE",
    "AMINO_ACID": "SMALL_MOLECULE",
    "CANCER": "CANCER",
    "CELL": "CELL_TYPE",
    "CELLULAR_COMPONENT": "CELLULAR_COMPONENT",
    "ORGANISM": "ORGANISM",
    "ORGANISM_SUBSTANCE": "SMALL_MOLECULE",
    "TISSUE": "TISSUE",
    "ORGAN": "ANATOMY",
    "ORGANISM_SUBDIVISION": "ANATOMY",
    "MULTI-TISSUE_STRUCTURE": "ANATOMY",   # scispaCy emits the hyphen form …
    "MULTI_TISSUE_STRUCTURE": "ANATOMY",   # … and the underscore form in some builds
    "ANATOMICAL_SYSTEM": "ANATOMY",
    "IMMATERIAL_ANATOMICAL_ENTITY": "ANATOMY",
    "PATHOLOGICAL_FORMATION": "PHENOTYPE",
    "DEVELOPING_ANATOMICAL_STRUCTURE": "DEVELOPMENTAL_STAGE",
}

_PACKAGES = ("en_ner_bc5cdr_md", "en_ner_jnlpba_md", "en_ner_bionlp13cg_md")


class Model(BaseNERModel):
    key = "scispacy_ensemble"
    name = "scispaCy Ensemble"
    model_id = " + ".join(_PACKAGES)
    description = "Three scispaCy NER pipelines merged (BC5CDR, JNLPBA, BioNLP13CG). Fast CPU baseline."
    license = "Apache-2.0 / CC BY-SA"
    homepage = "https://allenai.github.io/scispacy/"
    extras = ("scispacy", "spacy", *_PACKAGES)
    prefers_gpu = False

    def load(self) -> None:
        import spacy
        self._pipes = [spacy.load(p) for p in _PACKAGES]

    def _predict(self, text: str) -> list[Entity]:
        spans = {}
        for nlp in self._pipes:
            for ent in nlp(text).ents:
                key = (ent.start_char, ent.end_char)
                if key not in spans:
                    label = SCISPACY_MAP.get(ent.label_.upper(), ent.label_.upper())
                    spans[key] = Entity(ent.start_char, ent.end_char, ent.text, label)
        return list(spans.values())


_INSTANCE = None


def get_model() -> Model:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Model()
    return _INSTANCE
