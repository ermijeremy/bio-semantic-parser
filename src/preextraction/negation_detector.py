"""
Layer 4 — Negation Detector

NLI cross-encoder that classifies each entity's containing clause against the
hypothesis that the clause reports a confirmed positive finding.

Sentences are split at contrastive conjunctions ("but not", "however",
"although"…) before classification so that entities in the positive branch
of a contrastive sentence are not incorrectly flagged as negated.
"""
import os
import re

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch


_CONTRASTIVE = re.compile(
    r'\b(but not|however|although|whereas|while yet|despite|'
    r'in contrast|on the other hand|except|rather than|'
    r'but(?!\s+not)|yet(?!\s+not))\b',
    re.IGNORECASE,
)

def _extract_entity_clause(sentence: str, entity_text: str) -> str:
    """Return the sub-clause containing entity_text, or the full sentence if no split point."""
    parts = _CONTRASTIVE.split(sentence)
    if len(parts) <= 1:
        return sentence

    for part in parts:
        if len(part.split()) <= 2:
            continue
        if entity_text.lower() in part.lower():
            stripped = part.strip().strip(",;.")
            if len(stripped) > 10:
                return stripped

    return sentence


_DEFAULT_HYPOTHESIS = (
    "This study demonstrates a confirmed biological effect, finding, or association."
)


class NegationDetector:
    _MODEL     = "cross-encoder/nli-MiniLM2-L6-H768"
    try:
        _THRESHOLD = float(os.getenv("NEGATION_THRESHOLD", "0.45"))
    except ValueError:
        _THRESHOLD = 0.45
    # Calibrated against biomedical test sentences:
    # 0.45 catches "no improvement" (0.89), "NOT recommended" (0.47),
    # while correctly passing "contributes to" (0.03), "enables" (0.04).

    def __init__(self, hypothesis: str = _DEFAULT_HYPOTHESIS):
        self._hypothesis = hypothesis
        import os as _os
        _os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        self._tokenizer  = AutoTokenizer.from_pretrained(
            self._MODEL, local_files_only=True
        )
        self._model      = AutoModelForSequenceClassification.from_pretrained(
            self._MODEL,
            local_files_only=True,
            device_map=None,          # prevent accelerate meta tensor path
            low_cpu_mem_usage=False,  # force eager allocation
        )
        self._model.eval()
        # Label order: {0: contradiction, 1: entailment, 2: neutral}
    
    def _is_negated(self, clause: str) -> tuple:
        inputs = self._tokenizer(
            clause, self._hypothesis,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        with torch.no_grad():
            probs = torch.softmax(self._model(**inputs).logits, dim=-1)[0]
        contradiction_score = float(probs[0])
        return contradiction_score > self._THRESHOLD, round(contradiction_score, 3)

    def _find_sentence(self, doc, entity_text: str, start_char: int) -> str:
        if start_char >= 0:
            for sent in doc.sents:
                if sent.start_char <= start_char < sent.end_char:
                    return sent.text
        # PubTator3 entities lack char offsets — fall back to text search
        for sent in doc.sents:
            if entity_text.lower() in sent.text.lower():
                return sent.text
        return doc.text
    
    def process(self, entities: list, doc) -> dict:
        clause_cache: dict = {}
        updated = []
        negated = []

        for ent in entities:
            sentence = self._find_sentence(doc, ent["text"], ent.get("start", -1))
            clause   = _extract_entity_clause(sentence, ent["text"])

            if clause not in clause_cache:
                clause_cache[clause] = self._is_negated(clause)
            is_neg, confidence = clause_cache[clause]

            assertion = "ABSENT" if is_neg else "PRESENT"
            entry = {**ent, "negated": is_neg, "assertion": assertion, "confidence": confidence}
            updated.append(entry)
            if is_neg:
                negated.append(entry)

        return {
            "entities":         updated,
            "has_negation":     bool(negated),
            "negated_entities": negated,
        }
