"""
Layer 4 — Pre-Extraction Orchestrator
"""
import os
import spacy

from src.preextraction.ner_tagger import NERTagger
from src.preextraction.negation_detector import NegationDetector
from src.preextraction.doi_extractor import DOIExtractor
from src.preextraction.accession_detector import AccessionDetector
from src.preextraction.pubtator_client import fetch_pubtator_entities


def _load_model(env_key: str, default: str):
    """Load a spaCy model named by env_key, falling back to default. Returns None if empty."""
    name = os.getenv(env_key, default).strip()
    if not name:
        return None
    try:
        return spacy.load(name)
    except OSError:
        import sys
        print(f"[NER] Warning: model '{name}' ({env_key}) not found — skipping.", file=sys.stderr)
        return None


class Preextractor:
    def __init__(self):
        # NER_MODEL_1..N from env — add NER_MODEL_5, NER_MODEL_6 … to include new models.
        self._models = []
        n = 1
        while True:
            key     = f"NER_MODEL_{n}"
            default = {1:"en_ner_bc5cdr_md", 2:"en_ner_jnlpba_md",
                       3:"en_ner_bionlp13cg_md", 4:"en_core_sci_lg"}.get(n)
            if default is None and key not in os.environ:
                break          # no default and not in env — stop scanning
            model = _load_model(key, default or "")
            if model:
                self._models.append(model)
            n += 1
            if n > 20:         # safety cap — never scan beyond 20 slots
                break

        self.negation_detector  = NegationDetector()
        self.doi_extractor      = DOIExtractor()
        self.accession_detector = AccessionDetector()

    def _run_ensemble(self, text: str):
        """Run all loaded NER models and merge their spans, deduplicating overlaps."""
        if not self._models:
            import spacy as _sp
            nlp = _sp.blank("en")
            nlp.add_pipe("sentencizer")
            return nlp(text)

        base_doc  = self._models[0](text)
        span_data = [(e.start_char, e.end_char, e.label_) for e in base_doc.ents]

        for nlp in self._models[1:]:
            doc = nlp(text)
            span_data += [(e.start_char, e.end_char, e.label_) for e in doc.ents]

        all_spans = []
        for start, end, label in span_data:
            span = base_doc.char_span(start, end, label=label, alignment_mode="expand")
            if span is not None:
                all_spans.append(span)

        base_doc.ents = spacy.util.filter_spans(all_spans)
        return base_doc

    def process(self, chunk: dict) -> dict:
        text        = chunk["text"]
        doc         = self._run_ensemble(text)
        entities    = NERTagger.from_doc(doc)

        doc_id      = chunk.get("document_id", "")
        source_name = chunk.get("source_name", "")

        if source_name == "pubmed" and doc_id and len(doc_id) <= 10:
            pt_entities = fetch_pubtator_entities(doc_id)
            if pt_entities:
                entities = _merge_entities(entities, pt_entities)

        # ── HuggingFace clinical NER — adds Diagnostic_procedure, Therapeutic_procedure,
        #    Medication, Sign_symptom, Disease_disorder, Lab_value that scispaCy misses.
        try:
            from src.preextraction.hf_ner_tagger import tag_entities as _hf_tag, should_run as _hf_ok
            if _hf_ok():
                hf_ents = _hf_tag(text)
                if hf_ents:
                    entities = _merge_entities(entities, hf_ents)
        except Exception:
            pass   # never break the pipeline if optional tagger fails

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
