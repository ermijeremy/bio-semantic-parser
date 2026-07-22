"""
Layer 4 — Pre-Extraction Orchestrator

Five-model NER ensemble merged into a single span set. All spans from every
source are kept; on span overlap the earlier source in the ordered list wins.

These entities feed the Layer 6 LLM, which can only build
relations from pre-tagged entities (a missed span is a lost relation), so the
merge is a union — priority only decides the winning *type* on overlap.

  Source order (earlier wins on overlap)
  ──────────────────────────────────────
  1. scispaCy specialists — the 3 expert pipelines (BC5CDR, JNLPBA, BioNLP13CG),
     restricted to the types they are authoritative on: DISEASE, SMALL_MOLECULE,
     GENE, PROTEIN, CELL_TYPE, CELL_LINE, CANCER, NON_CODING_RNA.
  2. Stanza BioNLP13CG    — CharLM+BiLSTM+CRF; anatomy / organism / tissue breadth.
  3. GLiNER-BioMed Base   — zero-shot sweep to recover
                            borderline spans the larger models missed.
  4. scispaCy weak spans  — scispaCy spans whose mapped type is NOT a specialist
                            type (its shakier anatomy/organism guesses). Demoted
                            below the zero-shot models but still emitted as a
                            last-resort gap-filler so no recall is lost.

Every span carries its origin model (span._.source) and the model's confidence
(span._.score); NERTagger surfaces both, plus the exact model name in
span._.source_model, to the downstream entity dicts.

scispaCy models load eagerly in __init__ (fast, always run); Stanza and GLiNER
load lazily via singleton registry on first predict.
"""
from __future__ import annotations

import logging
import os

import spacy
from spacy.tokens import Span

from src.preextraction.ner_models import (
    Entity, SCISPACY_MAP,
    get_gliner_large as _get_gliner_large,
    # get_gliner_base  as _get_gliner_base,
    get_stanza       as _get_stanza,
)

from src.preextraction.ner_tagger import NERTagger
from src.preextraction import hf_ner_tagger
from src.preextraction.negation_detector import NegationDetector
from src.preextraction.doi_extractor import DOIExtractor
from src.preextraction.accession_detector import AccessionDetector
from src.preextraction.entity_validator import validate_entities
from src.preextraction.pubtator_client import fetch_pubtator_entities

_log = logging.getLogger(__name__)

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
if not Span.has_extension("source_model"):
    Span.set_extension("source_model", default="")


# ── merge helpers ─────────────────────────────────────────────────────────────

def _char_overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """True if the two character-level spans share at least one character."""
    return max(a_start, b_start) < min(a_end, b_end)


def _overlaps_any(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    """True if [start, end) overlaps ANY existing span."""
    return any(_char_overlaps(start, end, s, e) for s, e in occupied)


class Preextractor:
    """Five-model NER ensemble with lazy, cached model loading."""

    def __init__(self):
        # scispaCy expert pipelines (always loaded at init — fast, always run).
        for name, attr in [
            ("en_ner_bc5cdr_md",     "_nlp_bc5"),
            ("en_ner_jnlpba_md",     "_nlp_jnl"),
            ("en_ner_bionlp13cg_md", "_nlp_bio"),
        ]:
            try:
                setattr(self, attr, spacy.load(name))
                _log.info("[NER] loaded scispaCy %s", name)
            except OSError:
                _log.exception("[NER] FAILED to load scispaCy %s — ensemble will be incomplete", name)
                setattr(self, attr, None)

        # Stanza + GLiNER load lazily on first predict via registry singletons.
        self._stanza       = None   # Stanza BioNLP13CG
        self._gliner_large = None   # GLiNER-BioMed Large
        # self._gliner_base = None   # GLiNER-BioMed Base

        self.negation_detector  = NegationDetector()
        self.doi_extractor      = DOIExtractor()
        self.accession_detector = AccessionDetector()

    # ── lazy model accessors ────────────────────────────────────────────────────

    def _stanza_model(self):
        if self._stanza is None:
            _log.info("[NER] lazy-loading Stanza BioNLP13CG…")
            self._stanza = _get_stanza()
        return self._stanza

    def _gliner_large_model(self):
        if self._gliner_large is None:
            _log.info("[NER] lazy-loading GLiNER-BioMed Large…")
            self._gliner_large = _get_gliner_large()
        return self._gliner_large

    # def _gliner_base_model(self):
    #     if self._gliner_base is None:
    #         _log.info("[NER] lazy-loading GLiNER-BioMed Base…")
    #         self._gliner_base = _get_gliner_base()
    #     return self._gliner_base

    # ── ensemble ──────────────────────────────────────────────────────────────

    def _run_ensemble(self, text: str):
        # scispaCy expert pipelines run first. doc1 is the Doc returned and
        # populated, it is both the char_span factory for every source and the
        # sentence source NegationDetector relies on (doc.sents), so the
        # downstream contract is preserved.
        docs = []
        for name, model_name, nlp in [
            ("bc5cdr", "en_ner_bc5cdr_md", self._nlp_bc5),
            ("jnlpba", "en_ner_jnlpba_md", self._nlp_jnl),
            ("bionlp13cg", "en_ner_bionlp13cg_md", self._nlp_bio),
        ]:
            if nlp is None:
                _log.warning("[NER] skipping scispaCy %s — not loaded", name)
                continue
            docs.append((name, model_name, nlp(text)))
        if not docs:
            _log.error("[NER] no scispaCy models loaded — NER ensemble empty")

        # Map every raw scispaCy span to a schema type, then split by confidence:
        # specialist types lead the merge; everything else is demoted to a
        # last-resort gap-filler 
        scispacy_specialist: list[Entity] = []
        scispacy_weak:       list[Entity] = []
        for _, model_name, doc in docs:
            for e in doc.ents:
                label = SCISPACY_MAP.get(e.label_.upper(), "OTHER")
                ent = Entity(
                    e.start_char, e.end_char, e.text, label, 1.0,
                    source="scispacy", source_model=model_name,
                )
                if label in _SCISPACY_SPECIALIST:
                    scispacy_specialist.append(ent)
                else:
                    scispacy_weak.append(ent)

        # Ordered sources, earlier wins on span overlap. Non-overlapping spans
        # from every source are all kept (union); the zero-shot models' native
        # thresholds live in their own modules and are reached via .predict().
        sources: list[tuple[str, list[Entity]]] = [
            ("scispacy",      scispacy_specialist),
            ("stanza",        self._stanza_model().predict(text)),
            ("gliner_large",  self._gliner_large_model().predict(text)),
            # ("gliner_base",   self._gliner_base_model().predict(text)),
            ("scispacy_weak", scispacy_weak),
        ]

        occupied: list[tuple[int, int]] = []
        final_spans = []
        # Use the first available doc as the char_span factory
        span_doc = docs[0][2] if docs else None
        for source_name, ents in sources:
            stage_spans = []
            for ent in ents:
                if span_doc is None:
                    _log.warning("[NER] no doc available for char_span — skipping %r", ent.text)
                    continue
                span = span_doc.char_span(ent.start, ent.end, label=ent.label,
                                         alignment_mode="expand")
                if span is None:
                    _log.debug("char_span returned None for %r [%d:%d] from %s",
                               ent.text, ent.start, ent.end, source_name)
                    continue
                # Check overlap using the EXPANDED span bounds 
                if _overlaps_any(span.start_char, span.end_char, occupied):
                    continue
                span._.score  = ent.score
                span._.source = source_name
                span._.source_model = ent.source_model or ent.source or source_name
                stage_spans.append(span)
            stage_spans = spacy.util.filter_spans(stage_spans)
            final_spans.extend(stage_spans)
            occupied.extend((s.start_char, s.end_char) for s in stage_spans)

        # Sources are already mutually non-overlapping (each stage masks against
        # all prior stages), so this final pass only sorts + guards exact dups.
        if span_doc is not None:
            span_doc.ents = spacy.util.filter_spans(
                sorted(final_spans, key=lambda s: (s.start_char, -(s.end_char - s.start_char)))
            )
        return span_doc

    # ── public API ────────────────────────────────────────────────────────────

    def process(self, chunk: dict) -> dict:
        text        = chunk["text"]
        doc         = self._run_ensemble(text)
        entities    = NERTagger.from_doc(doc)

        # HuggingFace clinical NER — adds PROCEDURE / CLINICAL_INTERVENTION / DRUG /
        # SYMPTOM / CLINICAL_MEASUREMENT types that no ensemble model covers.
        if hf_ner_tagger.should_run():
            hf_entities = hf_ner_tagger.tag_entities(text)
            if hf_entities:
                entities = _merge_entities(entities, hf_entities)

        doc_id      = chunk.get("document_id", "")
        source_name = chunk.get("source_name", "")

        if source_name == "pubmed" and doc_id and len(doc_id) <= 10:
            pt_entities = fetch_pubtator_entities(doc_id)
            if pt_entities:
                entities = _merge_entities(entities, pt_entities)

        # LLM entity validation — shorten long spans, refine vague ones
        entities = validate_entities(entities, text)

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
        import concurrent.futures as _cf
        try:
            workers_env = int(os.getenv("NER_CHUNK_CONCURRENCY", "4"))
        except ValueError:
            workers_env = 4
        workers = min(workers_env, len(chunks))
        if workers <= 1 or len(chunks) <= 1:
            return [self.process(chunk) for chunk in chunks]
        with _cf.ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self.process, chunks))


def _merge_entities(ensemble: list, extra: list) -> list:
    """Merge entity lists by surface text. If extra has richer normalization (e.g. PubTator identifier), update the existing entry."""
    merged = []
    by_key = {}
    for e in ensemble:
        key = (e.get("text") or "").lower()
        if not key or key in by_key:
            continue
        by_key[key] = e.copy()
        merged.append(by_key[key])
    for e in extra:
        key = (e.get("text") or "").lower()
        if not key:
            continue
        if key not in by_key:
            by_key[key] = e.copy()
            merged.append(by_key[key])
        elif "identifier" in e or e.get("source") == "pubtator3":
            by_key[key].update(e)
    return merged
