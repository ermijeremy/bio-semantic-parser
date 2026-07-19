"""
Compare current NERTagger vs an improved variant on the TEST text.

Isolates the two TAGGER-level effects that were flagged:
  1. dedup       — current dedups by normalized text GLOBALLY, so every repeat
                   mention (at a different offset) is dropped. Improved dedups by
                   (normalized, start_char), keeping distinct mentions.
  2. _is_valid   — current drops any span starting with '[' or '(' and needs
                   >=30% alpha over the RAW text. Improved strips surrounding
                   brackets first, so tokens like "(HBPM)" / "[Ca2+]" survive,
                   while pure numeric / stat-notation spans are still dropped.

(Merge quality is NOT a tagger concern — it lives in preextractor.py's ensemble
and needs all 5 models. Not covered here.)

The entity set is produced by the 3 scispaCy models over TEST (union of spans),
then handed to each tagger. Run:
    env/bin/python -m src.preextraction.compare_ner_tagger
"""
import spacy

from src.preextraction.ner_tagger import NERTagger
from src.preextraction.test_ner_tagger import TEXT as TEST


# ── improved tagger ───────────────────────────────────────────────────────────

def _is_valid_improved(text: str) -> bool:
    """Strip surrounding brackets, then judge the core; keep bracketed bio tokens."""
    t = text.strip()
    if len(t) < 2:
        return False
    core = t.strip("[](){}").strip()
    if len(core) < 2:
        return False
    alpha = sum(c.isalpha() for c in core)
    if alpha == 0:                       # pure numeric / "R2=.04" / "[1]"
        return False
    return alpha / len(core) >= 0.30


def from_doc_improved(doc) -> list:
    seen, entities = set(), []
    for ent in doc.ents:
        if not _is_valid_improved(ent.text):
            continue
        normalized = ent.text.lower().strip()
        key = (normalized, ent.start_char)      # keep repeat mentions
        if key in seen:
            continue
        seen.add(key)
        entities.append({
            "text": ent.text, "normalized": normalized, "label": ent.label_,
            "start": ent.start_char, "end": ent.end_char,
        })
    return entities


# ── realistic entity set from the 3 scispaCy models ───────────────────────────

def build_doc(text: str):
    nlp_bc5 = spacy.load("en_ner_bc5cdr_md")
    nlp_jnl = spacy.load("en_ner_jnlpba_md")
    nlp_bio = spacy.load("en_ner_bionlp13cg_md")
    base = nlp_bc5(text)
    spans = []
    for nlp in (nlp_bc5, nlp_jnl, nlp_bio):
        for e in nlp(text).ents:
            s = base.char_span(e.start_char, e.end_char, label=e.label_,
                               alignment_mode="expand")
            if s is not None:
                spans.append(s)
    base.ents = spacy.util.filter_spans(spans)
    return base


# ── report ────────────────────────────────────────────────────────────────────

def main():
    doc = build_doc(TEST)
    raw = len(doc.ents)

    cur = NERTagger.from_doc(doc)
    imp = from_doc_improved(doc)

    cur_norms = {e["normalized"] for e in cur}
    cur_keys  = {(e["normalized"], e["start"]) for e in cur}

    print(f"raw spans from scispaCy union : {raw}")
    print(f"current tagger output         : {len(cur)}")
    print(f"improved tagger output        : {len(imp)}\n")

    # --- effect 1: dedup — mentions the improved tagger recovers ---
    recovered = [e for e in imp if e["normalized"] in cur_norms
                 and (e["normalized"], e["start"]) not in cur_keys]
    from collections import Counter
    lost = Counter(e["normalized"] for e in recovered)
    print(f"[dedup] repeat mentions dropped by current, kept by improved: {len(recovered)}")
    for norm, n in lost.most_common(12):
        print(f"        {n:3d}x  {norm!r}")

    # --- effect 2: _is_valid — spans current drops but improved keeps ---
    imp_only_text = [e for e in imp
                     if not NERTagger._is_valid(e["text"])
                     and _is_valid_improved(e["text"])]
    uniq = sorted({e["text"] for e in imp_only_text})
    print(f"\n[_is_valid] bracketed/edge spans current drops, improved keeps: {len(uniq)}")
    for t in uniq[:20]:
        print(f"        {t!r}")


if __name__ == "__main__":
    main()
