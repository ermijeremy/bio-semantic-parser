"""Evaluation harness: exact/partial span metrics + per-model corpus scoring.

Adapted from src/models_experiment/ner_comparison.ipynb. GPU memory tracking is
optional — it is only reported when torch+CUDA are available.
"""
from __future__ import annotations

import time
from collections import defaultdict

from .corpus import CORPUS
from .schema import ALL_TYPES, TIER_1_NLP_DETECTABLE


def _cuda():
    """Return the torch.cuda module if usable, else None (keeps torch optional)."""
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda
    except Exception:
        pass
    return None


def compute_metrics(gold_spans, pred_spans) -> dict:
    """Exact and partial (overlap, same-type) match precision/recall/F1."""
    gold_set = set((s, e, t.upper()) for s, e, _, t in gold_spans)
    pred_set = set((s, e, t.upper()) for s, e, _, t in pred_spans)

    tp_exact = len(gold_set & pred_set)
    prec_e = tp_exact / len(pred_set) if pred_set else 0
    rec_e = tp_exact / len(gold_set) if gold_set else 0
    f1_e = 2 * prec_e * rec_e / (prec_e + rec_e) if (prec_e + rec_e) else 0

    matched_g, matched_p = set(), set()
    for g in gold_set:
        for p in pred_set:
            if g[0] < p[1] and p[0] < g[1] and g[2] == p[2]:
                matched_g.add(g)
                matched_p.add(p)
    prec_p = len(matched_p) / len(pred_set) if pred_set else 0
    rec_p = len(matched_g) / len(gold_set) if gold_set else 0
    f1_p = 2 * prec_p * rec_p / (prec_p + rec_p) if (prec_p + rec_p) else 0

    return {
        "exact_precision": round(prec_e, 3), "exact_recall": round(rec_e, 3), "exact_f1": round(f1_e, 3),
        "partial_precision": round(prec_p, 3), "partial_recall": round(rec_p, 3), "partial_f1": round(f1_p, 3),
        "tp_exact": tp_exact, "fp": len(pred_set) - len(matched_p), "fn": len(gold_set) - len(matched_g),
    }


def _to_tuples(entities) -> list:
    """Accept list[Entity] or list[tuple] and normalise to (s, e, text, label)."""
    out = []
    for ent in entities:
        if hasattr(ent, "as_tuple"):
            out.append(ent.as_tuple())
        else:
            out.append(tuple(ent))
    return out


def evaluate_model(model_name, predict_fn, corpus=CORPUS) -> dict:
    """Run predict_fn over the corpus and compute overall/tier-1/per-type metrics."""
    cuda = _cuda()
    all_gold, all_pred = [], []
    latencies, gpu_mem, errors = [], [], []

    for sentence, gold_entities in corpus:
        if cuda:
            cuda.reset_peak_memory_stats()

        t0 = time.perf_counter()
        try:
            predicted = _to_tuples(predict_fn(sentence))
        except Exception as ex:
            predicted = []
            errors.append({"sentence": sentence[:70], "error": str(ex)})

        latencies.append((time.perf_counter() - t0) * 1000)
        if cuda:
            gpu_mem.append(cuda.max_memory_allocated() / 1e6)

        all_gold.extend(gold_entities)
        all_pred.extend(predicted)

    overall = compute_metrics(all_gold, all_pred)

    per_type = {}
    for etype in set(t.upper() for _, _, _, t in all_gold):
        g = [(s, e, tx, t) for s, e, tx, t in all_gold if t.upper() == etype]
        p = [(s, e, tx, t) for s, e, tx, t in all_pred if t.upper() == etype]
        per_type[etype] = compute_metrics(g, p)

    types_pred = set(t.upper() for _, _, _, t in all_pred)
    schema_types = set(ALL_TYPES) - {"OTHER"}
    coverage_pct = round(len(types_pred & schema_types) / len(schema_types) * 100, 1)

    t1_g = [(s, e, tx, t) for s, e, tx, t in all_gold if t.upper() in TIER_1_NLP_DETECTABLE]
    t1_p = [(s, e, tx, t) for s, e, tx, t in all_pred if t.upper() in TIER_1_NLP_DETECTABLE]
    tier1_metrics = compute_metrics(t1_g, t1_p)

    lats = sorted(latencies)
    return {
        "model": model_name,
        "overall": overall,
        "tier1_only": tier1_metrics,
        "per_type": per_type,
        "type_coverage_pct": coverage_pct,
        "types_predicted": sorted(types_pred),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "p95_latency_ms": round(lats[int(0.95 * len(lats))], 1) if lats else 0,
        "gpu_peak_mb": round(max(gpu_mem), 1) if gpu_mem else 0,
        "errors": errors,
        "n_sentences": len(corpus),
    }
