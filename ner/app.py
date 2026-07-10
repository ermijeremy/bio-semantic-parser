"""Flask dashboard to compare BioNER models.

Two workflows:
  1. Extract — run selected models on an ad-hoc sentence, view highlighted
     entities side by side with per-model latency.
  2. Benchmark — score selected models against the 69-sentence gold corpus and
     compare F1 / coverage / latency.

Models load lazily on first use; nothing downloads until you pick a model.
Run from the repo root:  python -m ner.app
"""
from __future__ import annotations

import time
import traceback

from flask import Flask, jsonify, render_template, request

from .corpus import CORPUS, corpus_stats
from .evaluation import evaluate_model
from .models import list_models, load_model
from .schema import ALL_TYPES, tier_of

app = Flask(__name__)

# Cache benchmark results per model key so re-runs are instant.
_BENCH_CACHE: dict = {}


@app.route("/")
def index():
    return render_template(
        "index.html",
        models=list_models(),
        corpus=corpus_stats(),
        entity_types=[t for t in ALL_TYPES if t != "OTHER"],
    )


@app.route("/api/models")
def api_models():
    return jsonify(list_models())


@app.route("/api/predict", methods=["POST"])
def api_predict():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    keys = data.get("models") or []
    if not text:
        return jsonify({"error": "No text provided."}), 400

    results = []
    for key in keys:
        entry = {"key": key}
        try:
            model = load_model(key)
            was_loaded = model._loaded
            t0 = time.perf_counter()
            ents = model.predict(text)
            elapsed = (time.perf_counter() - t0) * 1000
            entry.update({
                "entities": [
                    {"start": e.start, "end": e.end, "text": e.text,
                     "label": e.label, "tier": tier_of(e.label),
                     "score": round(float(e.score), 3)}
                    for e in sorted(ents, key=lambda x: x.start)
                ],
                "latency_ms": round(elapsed, 1),
                "cold_start": not was_loaded,
            })
        except Exception as ex:
            entry["error"] = f"{type(ex).__name__}: {ex}"
            entry["trace"] = traceback.format_exc()
        results.append(entry)
    return jsonify({"text": text, "results": results})


@app.route("/api/benchmark", methods=["POST"])
def api_benchmark():
    data = request.get_json(force=True)
    keys = data.get("models") or []
    force = bool(data.get("force"))

    results = []
    for key in keys:
        if not force and key in _BENCH_CACHE:
            results.append(_BENCH_CACHE[key])
            continue
        meta = next((m for m in list_models() if m["key"] == key), {})
        name = meta.get("name", key)
        try:
            model = load_model(key)
            report = evaluate_model(name, model.predict, CORPUS)
            report["key"] = key
            report["ok"] = True
            _BENCH_CACHE[key] = report
            results.append(report)
        except Exception as ex:
            results.append({
                "key": key, "model": name, "ok": False,
                "error": f"{type(ex).__name__}: {ex}",
            })
    # Rank successful runs by partial F1.
    ok = [r for r in results if r.get("ok")]
    ok.sort(key=lambda r: r["overall"]["partial_f1"], reverse=True)
    return jsonify({"results": results, "ranking": [r["key"] for r in ok]})


if __name__ == "__main__":
    import os
    port = int(os.getenv("NER_UI_PORT", "5001"))
    print(f"\n  BioNER comparison UI → http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
