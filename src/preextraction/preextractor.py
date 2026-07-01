"""
Layer 4 — Pre-Extraction Orchestrator

Runs three scispaCy NER models in ensemble, merges spans, applies PubTator3
normalization for PubMed articles, then classifies each entity's containing
clause for negation using an NLI cross-encoder.
"""
import spacy
from gliner import GLiNER

from src.preextraction.ner_tagger import NERTagger
from src.preextraction.negation_detector import NegationDetector
from src.preextraction.doi_extractor import DOIExtractor
from src.preextraction.accession_detector import AccessionDetector
from src.preextraction.pubtator_client import fetch_pubtator_entities

from src.schema.taxonomy import GLINER_LABELS, GLINER_MAP

class Preextractor:
    def __init__(self):
        self._nlp_bc5 = spacy.load("en_ner_bc5cdr_md")     # DISEASE, CHEMICAL
        self._nlp_jnl = spacy.load("en_ner_jnlpba_md")     # DNA, RNA, PROTEIN, CELL_TYPE, CELL_LINE
        self._nlp_bio = spacy.load("en_ner_bionlp13cg_md")  # GENE_OR_GENE_PRODUCT, CANCER, ORGANISM, TISSUE
        self._gliner  = GLiNER.from_pretrained("Ihor/gliner-biomed-large-v1.0")

        self.negation_detector  = NegationDetector()
        self.doi_extractor      = DOIExtractor()
        self.accession_detector = AccessionDetector()

    def _run_ensemble(self, text: str):
        doc1 = self._nlp_bc5(text)
        doc2 = self._nlp_jnl(text)
        doc3 = self._nlp_bio(text)

        gliner_ents = self._gliner.predict_entities(text, GLINER_LABELS, threshold=0.5, flat_ner=True)

        span_data = (
            [(e.start_char, e.end_char, e.label_) for e in doc1.ents]
            + [(e.start_char, e.end_char, e.label_) for e in doc2.ents]
            + [(e.start_char, e.end_char, e.label_) for e in doc3.ents]
            + [(e["start"], e["end"], GLINER_MAP.get(e["label"], "OTHER")) for e in gliner_ents]
        )
        all_spans = []
        for start, end, label in span_data:
            span = doc1.char_span(start, end, label=label, alignment_mode="expand")
            if span is not None:
                all_spans.append(span)

        doc1.ents = spacy.util.filter_spans(all_spans)
        return doc1

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

        negation    = self.negation_detector.process(entities, doc)
        doi         = self.doi_extractor.extract(text)
        accessions  = self.accession_detector.extract(text)

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
