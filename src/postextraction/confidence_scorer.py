"""Computes extraction confidence from five evidence channels using Open Targets weighted harmonic sum."""
import re


# Channel weights for the weighted harmonic sum (Open Targets approach).
# C2 highest: Kilicoglu 2017 showed epistemic certainty is the dominant signal for predication reliability.
# C3 second: a p-value or effect size is the gold standard of evidence quality (CI, p-value, SE).
# C1/C4 are corroborating signals; C5 lowest: Shen 2025 showed 41% LLM miscalibration.
CHANNEL_WEIGHTS = {
    "C1_section":      0.20,   # Open Targets text mining section weights
    #how certain is the language
    "C2_factuality":   0.30,   # Kilicoglu 2017 epistemic certainty (dominant)
    #Is there a p-value or effect size backing this up
    "C3_quantitative": 0.25,   # p-value / effect size (gold standard evidence)
    "C4_direct_claim": 0.15,   # co-sentence presence
    "C5_llm":          0.10,   # LLM reliability (Shen 2025: 41% miscalibration)
}


def score(
    subject_name: str,
    object_name: str,
    negated: bool,
    llm_confidence: float,
    section: str,
    text: str,
    relation: str = "",
    reasoning: str = "",
) -> float:
    """Compute extraction confidence from five evidence channels; returns float in [0,1]."""
    text_lc  = text.lower()
    sec      = section.lower()
    subj_key = subject_name.lower()[:12]
    obj_key  = object_name.lower()[:12]

    # Extract the most relevant sentence for NLI channels (C2 + C5).
    # NLI models are calibrated for short sentence pairs, not full chunks.
    # Using the whole chunk gives near-zero entailment even for correct triples.
    hyp       = f"{subject_name} {relation} {object_name}"
    best_sent = _best_sentence(text, subj_key, obj_key,
                               reasoning=reasoning,
                               relation_hypothesis=hyp)

    c1 = _channel_section(sec)
    c2 = _channel_factuality(best_sent, best_sent.lower())
    c3 = _channel_quantitative(text_lc)          # keep full chunk for stats
    c4 = _channel_direct_claim(text_lc, subj_key, obj_key)
    c5 = _channel_nli_entailment(best_sent, subject_name, relation, object_name,
                                 llm_fallback=float(llm_confidence or 0.5))

    combined = _combine_channels([c1, c2, c3, c4, c5])

    # Negated relations: cap at 0.65
    if negated:
        combined = min(combined, 0.65)

    return round(min(max(combined, 0.0), 1.0), 4)


# ── Sentence extractor ───────────────────────────────────────────────────────

_NEGATION_NEAR = re.compile(
    r'\b(did not|does not|do not|no|not|never|neither|nor|without|'
    r'fail|failed|lack|lacks|absent|exclude|excluded|unlikely|cannot)\b',
    re.I
)


def _best_sentence(text: str, subj_key: str, obj_key: str,
                   reasoning: str = "",
                   relation_hypothesis: str = "") -> str:
    """Return the sentence most relevant for NLI scoring."""
    # Priority 1: quoted reasoning trace with both entities
    if reasoning:
        quoted = re.findall(r"['\"]([^'\"]{20,200})['\"]", reasoning)
        for q in quoted:
            if subj_key in q.lower() and obj_key in q.lower():
                return q[:512]

    sentences   = re.split(r'(?<=[.!?])\s+', text.strip())
    with_both   = []
    with_one    = []

    for sent in sentences:
        sl = sent.lower()
        has_subj = subj_key in sl
        has_obj  = obj_key  in sl
        if has_subj and has_obj:
            if not _NEGATION_NEAR.search(sl):
                with_both.append(sent)
        elif has_subj or has_obj:
            with_one.append(sent)

    if not with_both and not with_one:
        # Last resort — first sentence with either entity key
        for sent in sentences:
            sl = sent.lower()
            if subj_key in sl or obj_key in sl:
                return sent[:512]
        return (sentences[0] if sentences else text)[:512]

    if not relation_hypothesis:
        # No hypothesis to rank by — return first clean match
        return (with_both or with_one)[0][:512]

    # Always include BOTH pools in NLI ranking (with_both first, then with_one).
    # This handles abbreviation mismatches: "blood pressure" in text vs "BP" in KG —
    # the best sentence might be in with_one if the object appears in expanded form.
    # NLI picks the sentence that best entails the relation regardless of key match.
    # Cap at 5 candidates — beyond this NLI ranking gives diminishing returns
    # and becomes the dominant cost for full-text papers (90+ relations).
    pool = (with_both + with_one)[:5]
    best_sent, best_score = pool[0], -1.0
    for sent in pool:
        _, ent, _ = _nli_score(sent[:512], relation_hypothesis)
        if ent > best_score:
            best_score = ent
            best_sent  = sent

    return best_sent[:512]


# ── Channel implementations ───────────────────────────────────────────────────

def _channel_section(section: str) -> float:
    """Channel 1 — Open Targets section weight (Kafkas 2017, PMC5461726), normalised to [0,1]."""
    _OT_WEIGHTS = {
        "results":     5, "result":      5,
        "figures":     5, "figure":      5, "tables": 5,
        "abstract":    3,
        "discussion":  2, "conclusion":  2, "conclusions": 2,
        "methods":     1, "method":      1, "background":  1,
        "introduction":1,
    }
    return _OT_WEIGHTS.get(section, 2) / 5.0


def _get_nli_model():
    """Shared NLI model singleton — loaded once, reused by C2 and C5; returns (tok, model) or (None, None)."""
    if not hasattr(_get_nli_model, "_loaded"):
        try:
            import os
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            import torch
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            _MODEL_NAME = "cross-encoder/nli-MiniLM2-L6-H768"
            tok   = AutoTokenizer.from_pretrained(_MODEL_NAME, local_files_only=True)
            model = AutoModelForSequenceClassification.from_pretrained(
                _MODEL_NAME,
                local_files_only=True,
                device_map=None,          # never use accelerate's meta tensor path
                low_cpu_mem_usage=False,  # force full eager allocation
            )
            # Explicitly materialize all tensors onto a real device
            # This guarantees no meta tensors remain regardless of accelerate state
            if torch.cuda.is_available():
                _device = torch.device("cuda")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                _device = torch.device("mps")
            else:
                _device = torch.device("cpu")
            model = model.to(_device)
            model.eval()
            _get_nli_model._tok    = tok
            _get_nli_model._model  = model
            _get_nli_model._device = _device
            _get_nli_model._torch  = torch
        except Exception:
            _get_nli_model._tok   = None
            _get_nli_model._model = None
            _get_nli_model._torch = None
        _get_nli_model._loaded = True
    return _get_nli_model._tok, _get_nli_model._model


def _nli_score(premise: str, hypothesis: str):
    """
    Run NLI and return (contradiction, entailment, neutral) probabilities.
    Returns (0.33, 0.33, 0.33) if model unavailable.
    """
    tok, model = _get_nli_model()
    if tok is None:
        return 0.33, 0.33, 0.33
    torch  = _get_nli_model._torch
    device = getattr(_get_nli_model, "_device", torch.device("cpu"))
    inputs = tok(premise, hypothesis, return_tensors="pt",
                 truncation=True, max_length=512)
    # Move inputs to same device as model to avoid meta tensor mismatch
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        probs = torch.softmax(model(**inputs).logits, dim=-1)[0]
    # Label order: {0: contradiction, 1: entailment, 2: neutral}
    return float(probs[0]), float(probs[1]), float(probs[2])


def _channel_factuality(text: str, text_lc: str) -> float:
    """Channel 2 — NLI epistemic certainty; falls back to Kilicoglu 2017 regex (PMC5497973)."""
    _, entailment, _ = _nli_score(text,
        "This sentence makes a definitive, confirmed factual claim.")

    if entailment > 0.33:
        # NLI available and confident — return entailment score directly
        # Re-scale from [0,1] to match Kilicoglu factuality range [0.20, 0.95]
        return 0.20 + entailment * 0.75
    else:
        # NLI unavailable or neutral — fall back to Kilicoglu 2017 regex
        _DOUBTFUL = (
            r"\b(unlikely|doubt|controversial|debate|disputed|contradict|"
            r"fail to|failed to|did not|no evidence|cannot confirm|"
            r"inconclusive|insufficient evidence)\b"
        )
        _POSSIBLE = (
            r"\b(may|might|could|possibly|potentially|presumably|perhaps|"
            r"unclear|uncertain|unknown|speculate|hypothesize|propose|"
            r"putative|preliminary|tentative)\b"
        )
        _PROBABLE = (
            r"\b(likely|probably|suggest|suggests|indicate|indicates|"
            r"appear|appears|seem|seems|consistent with|support|supports|"
            r"implies|correlate|associate|associated)\b"
        )
        _FACT = (
            r"\b(demonstrate|demonstrates|demonstrated|show|shows|showed|"
            r"prove|proves|confirm|confirms|confirmed|establish|establishes|"
            r"identify|identifies|reveal|reveals|observe|observed|detect|"
            r"detected|measure|measured|find|finds|found|report|reports|"
            r"determine|determines|determined)\b"
        )
        if re.search(_DOUBTFUL, text_lc): return 0.20
        if re.search(_POSSIBLE, text_lc): return 0.50
        if re.search(_PROBABLE, text_lc): return 0.75
        if re.search(_FACT,     text_lc): return 0.95
        return 0.65


def _channel_quantitative(text_lc: str) -> float:
    """Channel 3 — Open Targets p-value scaling (Ochoa 2021, NAR); no stats → 0.40."""
    _PVAL  = r"p\s*[<≤=]\s*(0\.\d+|1[eE]-\d+|\d+e-\d+)"
    _QUANT = (
        r"(\d+\.?\d*\s*%|\d+[.\-]\d*[\s-]?fold|hazard\s*ratio|"
        r"odds\s*ratio|relative\s*risk|confidence\s*interval|"
        r"standard\s*error|effect\s*size|beta\s*=|r\s*=\s*0\.\d)"
    )
    pval_m = re.search(_PVAL, text_lc)
    if pval_m:
        try:
            p = float(pval_m.group(1))
            if   p <= 0.001: return 1.00
            elif p <= 0.01:  return 0.85
            elif p <= 0.05:  return 0.75
            else:            return 0.55
        except ValueError:
            return 0.75
    if re.search(_QUANT, text_lc, re.I):
        return 0.70
    return 0.40


def _channel_direct_claim(text_lc: str, subj_key: str, obj_key: str) -> float:
    """Channel 4 — co-sentence presence: 0.90 if both entities in same sentence, else 0.35."""
    sentences = re.split(r"(?<=[.!?])\s+", text_lc)
    if any(subj_key in s and obj_key in s for s in sentences):
        return 0.90
    return 0.35


def _channel_nli_entailment(text: str, subject: str, relation: str, obj: str,
                             llm_fallback: float = 0.55) -> float:
    """Channel 5 — NLI P(entailment) for the extracted triple; falls back to calibrated LLM self-report."""
    hypothesis = f"{subject} {relation} {obj}"
    _, entailment, _ = _nli_score(text, hypothesis)
    # If NLI returned the fallback (0.33) the model wasn't available
    if entailment != 0.33:
        return entailment
    # Fallback: compress LLM self-report into [0.37, 0.77] to match NLI range
    return 0.37 + min(max(llm_fallback, 0.0), 1.0) * 0.40


# ── Weighted harmonic sum (Open Targets approach) ────────────────────────────

def _combine_channels(channels: list) -> float:
    """Open Targets weighted harmonic sum (Ochoa 2021, NAR): i² penalty dampens single-channel dominance."""
    weights = list(CHANNEL_WEIGHTS.values())
    ranked = sorted(zip(channels, weights), key=lambda x: x[0], reverse=True)
    numerator   = sum(w * c / (i + 1) ** 2 for i, (c, w) in enumerate(ranked))
    denominator = sum(w       / (i + 1) ** 2 for i, (_, w) in enumerate(ranked))
    return numerator / denominator if denominator else 0.0


# ── Public helper: explain a score ───────────────────────────────────────────

def explain(
    subject_name: str,
    object_name: str,
    negated: bool,
    llm_confidence: float,
    section: str,
    text: str,
    relation: str = "",
    reasoning: str = "",
) -> dict:
    """Return full per-channel score breakdown for audit and debugging."""
    text_lc  = text.lower()
    sec      = section.lower()
    subj_key = subject_name.lower()[:12]
    obj_key  = object_name.lower()[:12]
    llm_raw  = float(llm_confidence or 0.5)

    hyp2      = f"{subject_name} {relation} {object_name}"
    best_sent = _best_sentence(text, subj_key, obj_key,
                               reasoning=reasoning,
                               relation_hypothesis=hyp2)

    c1 = _channel_section(sec)
    c2 = _channel_factuality(best_sent, best_sent.lower())
    c3 = _channel_quantitative(text_lc)
    c4 = _channel_direct_claim(text_lc, subj_key, obj_key)
    c5 = _channel_nli_entailment(best_sent, subject_name, relation, object_name,
                                  llm_fallback=llm_raw)

    combined = _combine_channels([c1, c2, c3, c4, c5])
    if negated:
        combined = min(combined, 0.65)

    return {
        "final_score":          round(min(max(combined, 0.0), 1.0), 4),
        "channels": {
            "C1_section_weight":       round(c1, 4),
            "C2_factuality_nli":       round(c2, 4),
            "C3_quantitative_evidence":round(c3, 4),
            "C4_direct_claim":         round(c4, 4),
            "C5_nli_entailment":       round(c5, 4),
        },
        "inputs": {
            "section":          section,
            "llm_confidence":   llm_raw,
            "negated":          negated,
            "weights":          CHANNEL_WEIGHTS,
        },
        "references": {
            "combination_formula": "Open Targets weighted harmonic sum (Ochoa 2021, NAR)",
            "section_weights":     "Open Targets (Kafkas 2017, PMC5461726)",
            "factuality":          "Kilicoglu 2017 (PMC5497973)",
            "quantitative":        "Open Targets (Ochoa 2021, NAR)",
            "llm_reliability":     "INDRA (Bachman 2023, PMC10167483)",
        },
    }
