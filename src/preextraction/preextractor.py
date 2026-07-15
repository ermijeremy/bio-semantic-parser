"""
Layer 4 — Pre-Extraction Orchestrator

Five-model NER ensemble merged into a single span set. All spans from every
source are kept; on span overlap the earlier source in the ordered list wins.

these entities feed the Layer 6 LLM, which can only build
relations from pre-tagged entities (a missed span is a lost relation), so the
merge is a union — priority only decides the winning *type* on overlap.

  Source order (earlier wins on overlap)
  ──────────────────────────────────────
  1. scispaCy specialists — the 3 expert pipelines (BC5CDR, JNLPBA, BioNLP13CG),
     restricted to the types they are authoritative on: DISEASE, SMALL_MOLECULE,
     GENE, PROTEIN, CELL_TYPE, CELL_LINE, CANCER, NON_CODING_RNA.
  2. GLiNER-BioMed Large  — highest-F1 zero-shot model (~0.88), broadest coverage.
  3. Stanza BioNLP13CG    — CharLM+BiLSTM+CRF; anatomy / organism / tissue breadth.
  4. GLiNER-BioMed Base   — lighter zero-shot sweep (lower threshold) to recover
                            borderline spans the larger models missed.
  5. scispaCy weak spans  — scispaCy spans whose mapped type is NOT a specialist
                            type (its shakier anatomy/organism guesses). Demoted
                            below the zero-shot models but still emitted as a
                            last-resort gap-filler so no recall is lost.

Every span carries its origin model (span._.source) and the model's confidence
(span._.score); NERTagger surfaces both to the downstream entity dicts.

scispaCy models load eagerly in __init__ (fast, always run); Stanza and the two
GLiNER models load lazily via singleton registry on first predict.
"""
from __future__ import annotations

import spacy
from spacy.tokens import Span

from ner.base import Entity

from src.preextraction.ner_tagger import NERTagger
from src.preextraction.negation_detector import NegationDetector
from src.preextraction.doi_extractor import DOIExtractor
from src.preextraction.accession_detector import AccessionDetector
from src.preextraction.pubtator_client import fetch_pubtator_entities

# scispaCy raw-label → schema-type map (single source of truth, shared with the
# scispaCy ensemble model). Reached via the model module so it never drifts.
from ner.models.scispacy_ensemble import SCISPACY_MAP

# ── lazy model accessors ──────────────────────────────────────────────────────
# Imported here so the ner registry can manage singleton + cache env-vars.
from ner.models.gliner_biomed_large import get_model as _get_gliner_large
from ner.models.gliner_biomed_base  import get_model as _get_gliner_base
from ner.models.stanza_bionlp13cg   import get_model as _get_stanza


# Schema types scispaCy is authoritative on these win over the zero-shot models
# on span overlap. Any other scispaCy type is demoted to a last-resort gap-filler.
_SCISPACY_SPECIALIST = {
    "DISEASE", "SMALL_MOLECULE", "GENE", "PROTEIN",
    "CELL_TYPE", "CELL_LINE", "CANCER", "NON_CODING_RNA",
}

# Per-span provenance carried through doc.ents. Span extension values live in
# doc.user_data keyed by token offsets, so they survive the round-trip through
# `doc.ents = [...]` (new Span objects over the same offsets read the same value).
if not Span.has_extension("score"):
    Span.set_extension("score", default=1.0)
if not Span.has_extension("source"):
    Span.set_extension("source", default="")


# ── merge helpers ─────────────────────────────────────────────────────────────

def _char_overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """True if the two character-level spans share at least one character."""
    return max(a_start, b_start) < min(a_end, b_end)


def _covered_by(start: int, end: int, covered: list[tuple[int, int]]) -> bool:
    """True if [start, end) is fully covered by any span in *covered*."""
    for cs, ce in covered:
        if cs <= start and end <= ce:
            return True
    return False


def _overlaps_any(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    """True if [start, end) overlaps ANY existing span."""
    return any(_char_overlaps(start, end, s, e) for s, e in occupied)


class Preextractor:
    """Five-model NER ensemble with lazy, cached model loading."""

    def __init__(self):
        # scispaCy expert pipelines (always loaded at init — fast, always run).
        self._nlp_bc5 = spacy.load("en_ner_bc5cdr_md")       # DISEASE, CHEMICAL
        self._nlp_jnl = spacy.load("en_ner_jnlpba_md")       # DNA, RNA, PROTEIN, CELL_TYPE, CELL_LINE
        self._nlp_bio = spacy.load("en_ner_bionlp13cg_md")   # broad bio types

        # Stanza + both GLiNER models load lazily on first predict via registry
        # singletons no duplicate instantiation across Preextractor instances.
        self._stanza       = None   # Stanza BioNLP13CG
        self._gliner_large = None   # GLiNER-BioMed Large
        self._gliner_base  = None   # GLiNER-BioMed Base

        self.negation_detector  = NegationDetector()
        self.doi_extractor      = DOIExtractor()
        self.accession_detector = AccessionDetector()

    # ── lazy model accessors ────────────────────────────────────────────────────

    def _stanza_model(self):
        if self._stanza is None:
            self._stanza = _get_stanza()
        return self._stanza

    def _gliner_large_model(self):
        if self._gliner_large is None:
            self._gliner_large = _get_gliner_large()
        return self._gliner_large

    def _gliner_base_model(self):
        if self._gliner_base is None:
            self._gliner_base = _get_gliner_base()
        return self._gliner_base

    # ── ensemble ──────────────────────────────────────────────────────────────

    def _run_ensemble(self, text: str):
        # scispaCy expert pipelines run first. doc1 is the Doc returned and
        # populated, it is both the char_span factory for every source and the
        # sentence source NegationDetector relies on (doc.sents), so the
        # downstream contract is preserved.
        doc1 = self._nlp_bc5(text)
        doc2 = self._nlp_jnl(text)
        doc3 = self._nlp_bio(text)

        # Map every raw scispaCy span to a schema type, then split by confidence:
        # specialist types lead the merge; everything else is demoted to a
        # last-resort gap-filler 
        scispacy_specialist: list[Entity] = []
        scispacy_weak:       list[Entity] = []
        for doc in (doc1, doc2, doc3):
            for e in doc.ents:
                label = SCISPACY_MAP.get(e.label_.upper(), "OTHER")
                ent = Entity(e.start_char, e.end_char, e.text, label, 1.0)
                if label in _SCISPACY_SPECIALIST:
                    scispacy_specialist.append(ent)
                else:
                    scispacy_weak.append(ent)

        # Ordered sources, earlier wins on span overlap. Non-overlapping spans
        # from every source are all kept (union); the zero-shot models' native
        # thresholds live in their own modules and are reached via .predict().
        sources: list[tuple[str, list[Entity]]] = [
            ("scispacy",      scispacy_specialist),
            ("gliner_large",  self._gliner_large_model().predict(text)),
            ("stanza",        self._stanza_model().predict(text)),
            ("gliner_base",   self._gliner_base_model().predict(text)),
            ("scispacy_weak", scispacy_weak),
        ]

        occupied: list[tuple[int, int]] = []
        final_spans = []
        for source_name, ents in sources:
            stage_spans = []
            for ent in ents:
                if _overlaps_any(ent.start, ent.end, occupied):
                    continue  # an earlier, higher-priority source claimed this region
                span = doc1.char_span(ent.start, ent.end, label=ent.label,
                                      alignment_mode="expand")
                if span is None:
                    continue
                span._.score  = ent.score
                span._.source = source_name
                stage_spans.append(span)
            stage_spans = spacy.util.filter_spans(stage_spans)
            final_spans.extend(stage_spans)
            occupied.extend((s.start_char, s.end_char) for s in stage_spans)

        # Sources are already mutually non-overlapping (each stage masks against
        # all prior stages), so this final pass only sorts + guards exact dups.
        doc1.ents = spacy.util.filter_spans(
            sorted(final_spans, key=lambda s: (s.start_char, -(s.end_char - s.start_char)))
        )
        return doc1

    # ── public API ────────────────────────────────────────────────────────────

    def process(self, chunk: dict) -> dict:
        text     = chunk["text"]
        doc      = self._run_ensemble(text)
        entities = NERTagger.from_doc(doc)

        doc_id      = chunk.get("document_id", "")
        source_name = chunk.get("source_name", "")

        if source_name == "pubmed" and doc_id and len(doc_id) <= 10:
            pt_entities = fetch_pubtator_entities(doc_id)
            if pt_entities:
                entities = _merge_entities(entities, pt_entities)

        negation   = self.negation_detector.process(entities, doc)
        doi        = self.doi_extractor.extract(text)
        accessions = self.accession_detector.extract(text)

        original_pdf_hash = doc_id if len(doc_id) == 64 else None
        if doi and len(doc_id) == 64:
            doc_id = doi

        return {
            **chunk,
            "document_id":       doc_id,
            "original_pdf_hash": original_pdf_hash,
            "entities":          negation["entities"],
            "has_negation":      negation["has_negation"],
            "negated_entities":  negation["negated_entities"],
            "doi":               doi,
            "accession_numbers": accessions,
        }

    def process_batch(self, chunks: list) -> list:
        return [self.process(chunk) for chunk in chunks]


def _merge_entities(ensemble: list, pubtator: list) -> list:
    """PubTator3 entities (with normalization IDs) take priority; ensemble fills gaps."""
    pt_normalized = {e["normalized"] for e in pubtator}
    gap_fillers   = [e for e in ensemble if e["normalized"] not in pt_normalized]
    return pubtator + gap_fillers
