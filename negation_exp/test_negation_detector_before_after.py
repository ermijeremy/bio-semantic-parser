#!/usr/bin/env python3
"""Standalone before/after comparison test for the Layer 4 negation detector.

Commit 80c47c5 ("fix(preextraction): aggregate negation across all entity
contexts") replaced the detector's single-context, first-mention classification
("before") with all-context aggregation ("after"):

  before — each entity is judged from the ONE sentence containing its first
           mention, so the label depends on sentence order and an entity is
           negated (ABSENT) even when other sentences show it present.
  after  — every sentence mentioning the entity is classified; an entity is
           ABSENT only if negated in all contexts, MIXED when contexts
           conflict, otherwise PRESENT. Sentence order is irrelevant.

This script runs the REAL post-fix implementation from src/ plus a faithful
pre-fix reference against the same synthetic documents with a deterministic
mock NLI classifier, then asserts the behaviours the fix was meant to change.

Run:
    python negation_exp/test_negation_detector_before_after.py

Requires only the standard library. The real NLI model and its dependencies
(transformers, torch) are never loaded — the classifier is mocked.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _stub_heavy_deps() -> None:
    """Make src/preextraction/negation_detector.py importable without the model stack."""
    import types

    if "transformers" not in sys.modules:
        transformers = types.ModuleType("transformers")
        transformers.AutoTokenizer = None
        transformers.AutoModelForSequenceClassification = None
        sys.modules["transformers"] = transformers
    if "torch" not in sys.modules:
        torch = types.ModuleType("torch")
        torch.no_grad = lambda *args, **kwargs: None
        sys.modules["torch"] = torch


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class BeforeNegationDetector:
    """Reference implementation of the PRE-FIX detector (parent of commit 80c47c5).

    Each entity is classified against the single sentence containing its first
    mention (resolved by char offset, with a text-search fallback for entities
    lacking offsets). Later occurrences are ignored, so the label depends on
    sentence order. `_classify` is injected by the harness as the mock NLI.
    """

    def _find_sentence(self, doc, entity_text, start_char):
        if start_char >= 0:
            for sent in doc.sents:
                if sent.start_char <= start_char < sent.end_char:
                    return sent.text
        for sent in doc.sents:
            if entity_text.lower() in sent.text.lower():
                return sent.text
        return doc.text

    def process(self, entities, doc):
        clause_cache = {}
        updated = []
        negated = []

        for ent in entities:
            sentence = self._find_sentence(doc, ent["text"], ent.get("start", -1))
            clause = _extract_entity_clause(sentence, ent["text"])

            if clause not in clause_cache:
                clause_cache[clause] = self._classify(clause)
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


def _make_doc(sentences):
    """Build a minimal spaCy-like doc exposing `.sents` and `.text`."""
    text = " ".join(sentences)

    class Sent:
        pass

    sents = []
    pos = 0
    for text_i in sentences:
        sent = Sent()
        sent.text = text_i
        sent.start_char = pos
        sent.end_char = pos + len(text_i)
        sents.append(sent)
        pos += len(text_i) + 1

    doc = type("Doc", (), {"sents": sents, "text": text})()
    return doc


def _first_mention_start(doc, entity_text):
    """Offset of the first sentence in doc mentioning entity_text (-1 if none)."""
    low = entity_text.lower()
    for sent in doc.sents:
        if low in sent.text.lower():
            return sent.start_char
    return -1


def _make_entities(doc, entity_text, label="GENE"):
    start = _first_mention_start(doc, entity_text)
    return [{
        "text": entity_text,
        "normalized": entity_text.lower(),
        "label": label,
        "start": start,
        "end": start + len(entity_text),
        "negated": False,
        "assertion": "PRESENT",
        "confidence": 1.0,
    }]


NEGATION_CUES = ("absent", "not detected", "failed to", "does not", "without")


def mock_is_negated(clause):
    """Deterministic stand-in for the NLI model: content-based, order-independent."""
    is_neg = any(cue in clause.lower() for cue in NEGATION_CUES)
    return is_neg, round(0.92 if is_neg else 0.08, 3)


NEG_ABSENT_CELLS = "PARPis are absent from resistant cells."
POS_TREATS      = "PARPis treat breast cancer effectively."
NEG_NOT_DETECTED = "PARPis were not detected in the resistant lines."
POS_TARGETS     = "PARPis also target ovarian cancer."
NEG_GHOST_ABSENT = "Ghost cells are absent from the model."
NEG_GHOST_NODET = "Ghost cells were not detected."


def _entity_summary(result, entity_text):
    for ent in result["entities"]:
        if ent["text"] == entity_text:
            return {
                "assertion": ent["assertion"],
                "negated": ent["negated"],
                "contexts_checked": ent.get("contexts_checked"),
                "negated_contexts": ent.get("negated_contexts"),
            }
    raise AssertionError(f"entity {entity_text!r} not in result")


def _run_both(detector_before, detector_after, sentences, entity_text):
    doc = _make_doc(sentences)
    entities = _make_entities(doc, entity_text)
    before = _entity_summary(detector_before.process(entities, doc), entity_text)
    after = _entity_summary(detector_after.process(entities, doc), entity_text)
    return before, after


def main() -> int:
    _stub_heavy_deps()
    detector_module = _load_module(
        REPO_ROOT / "src" / "preextraction" / "negation_detector.py",
        "_negation_detector_real",
    )
    global _extract_entity_clause
    _extract_entity_clause = detector_module._extract_entity_clause

    before_detector = BeforeNegationDetector()
    before_detector._classify = mock_is_negated

    after_detector = detector_module.NegationDetector.__new__(
        detector_module.NegationDetector
    )
    after_detector._is_negated = mock_is_negated

    rows = []
    failures = []

    def check(condition, message):
        if condition:
            return
        failures.append(message)
        print(f"  FAIL: {message}")

    def record(name, before, after, expected_after, improvement_note):
        same_outcome = (before["assertion"], before["negated"]) == (after["assertion"], after["negated"])
        verdict = "SAME" if same_outcome else "IMPROVED"
        rows.append((name, before, after, verdict, improvement_note))
        for field, value in expected_after.items():
            check(after[field] == value, f"{name}: after.{field} = {after[field]!r}, expected {value!r}")

    before, after = _run_both(
        before_detector, after_detector, [NEG_ABSENT_CELLS, POS_TREATS], "PARPis"
    )
    record("S1 conflict, negation first",
           before, after,
           {"assertion": "MIXED", "negated": False, "contexts_checked": 2, "negated_contexts": 1},
           "before marks ABSENT from first mention alone; after sees both contexts")

    before_flipped, after_flipped = _run_both(
        before_detector, after_detector, [POS_TREATS, NEG_ABSENT_CELLS], "PARPis"
    )
    record("S2 conflict, order flipped",
           before_flipped, after_flipped,
           {"assertion": "MIXED", "negated": False, "contexts_checked": 2, "negated_contexts": 1},
           "after result identical to S1 (order-invariant)")

    check(before["assertion"] != before_flipped["assertion"],
          "S1/S2: before label changed with sentence order (ABSENT vs PRESENT)")
    check(after["assertion"] == after_flipped["assertion"],
          "S1/S2: after label is stable across sentence orders")
    check(after == after_flipped, "S1/S2: after result identical across orders")

    before, after = _run_both(
        before_detector, after_detector, [NEG_GHOST_ABSENT, NEG_GHOST_NODET], "Ghost cells"
    )
    record("S3 all contexts negated",
           before, after,
           {"assertion": "ABSENT", "negated": True, "contexts_checked": 2, "negated_contexts": 2},
           "both agree the entity is absent")

    before, after = _run_both(
        before_detector, after_detector, [POS_TREATS, POS_TARGETS], "PARPis"
    )
    record("S4 all contexts present",
           before, after,
           {"assertion": "PRESENT", "negated": False, "contexts_checked": 2, "negated_contexts": 0},
           "both agree the entity is present")

    before, after = _run_both(
        before_detector, after_detector, [NEG_ABSENT_CELLS, POS_TREATS, NEG_NOT_DETECTED], "PARPis"
    )
    record("S5 two of three contexts negated",
           before, after,
           {"assertion": "MIXED", "negated": False, "contexts_checked": 3, "negated_contexts": 2},
           "before marks ABSENT; after keeps PRESENT-with-conflict signal")

    doc = _make_doc([NEG_ABSENT_CELLS, POS_TREATS])
    entities = _make_entities(doc, "Mystery")
    before_result = before_detector.process(entities, doc)
    after_result = after_detector.process(entities, doc)
    before = _entity_summary(before_result, "Mystery")
    after = _entity_summary(after_result, "Mystery")
    record("S6 entity absent from document",
           before, after,
           {"assertion": "PRESENT", "negated": False, "contexts_checked": 0, "negated_contexts": 0},
           "before falls back to the whole doc and guesses; after stays PRESENT")

    print("\nScenario comparison (before = first-mention, after = all-contexts):")
    print(f"{'scenario':<32}{'before':<30}{'after':<32}{'verdict':<10}note")
    print("-" * 150)
    for name, before, after, verdict, note in rows:
        before_str = f"{before['assertion']}/neg={before['negated']}"
        after_str = (f"{after['assertion']}/neg={after['negated']} "
                     f"(ctx {after['contexts_checked']}/{after['negated_contexts']})")
        print(f"{name:<32}{before_str:<30}{after_str:<32}{verdict:<10}{note}")

    print(f"\n{len(rows)} scenarios, {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
