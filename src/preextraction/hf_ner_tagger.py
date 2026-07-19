"""
src/preextraction/hf_ner_tagger.py
────────────────────────────────────
HuggingFace transformer-based NER tagger — supplements the scispaCy ensemble
with clinical entity types that no scispaCy model covers:

  Diagnostic_procedure  → PROCEDURE / CLINICAL_INTERVENTION
  Therapeutic_procedure → CLINICAL_INTERVENTION / TREATMENT
  Medication            → DRUG
  Sign_symptom          → SYMPTOM
  Disease_disorder      → DISEASE
  Lab_value             → CLINICAL_MEASUREMENT

Model is configurable via .env:
    HF_NER_MODEL=d4data/biomedical-ner-all   (default)
    HF_NER_ENABLED=true/false                (default: true)
    HF_NER_THRESHOLD=0.80                    (min confidence score)

Label mapping from model output → our EntityType taxonomy is defined in
HF_LABEL_MAP below — extend it if you add a different model.
"""
from __future__ import annotations
import os
from typing import Optional

# Map model-specific labels → our EntityType taxonomy values
# Extend this dict when switching to a different HuggingFace model.
HF_LABEL_MAP: dict[str, str] = {
    # d4data/biomedical-ner-all labels
    "Diagnostic_procedure":  "PROCEDURE",
    "Therapeutic_procedure": "CLINICAL_INTERVENTION",
    "Medication":            "DRUG",
    "Sign_symptom":          "SYMPTOM",
    "Disease_disorder":      "DISEASE",
    "Lab_value":             "CLINICAL_MEASUREMENT",
    "Detailed_description":  "OTHER",
    "Activity":              "ACTIVITY",
    "Biological_structure":  "ANATOMY",
    "Clinical_event":        "EVENT",
    "Coreference":           "OTHER",
    "Date":                  "OTHER",
    "Dosage":                "OTHER",
    "Duration":              "OTHER",
    "Family_history":        "OTHER",
    "Frequency":             "OTHER",
    "History":               "OTHER",
    "Nonbiological_location":"OTHER",
    "Other_entity":          "OTHER",
    "Other_event":           "EVENT",
    "Personal_background":   "OTHER",
    "Qualitative_concept":   "OTHER",
    "Quantitative_concept":  "OTHER",
    "Severity":              "OTHER",
    "Time":                  "OTHER",
    "Volume":                "OTHER",
    "Weight":                "OTHER",
}

_pipeline: Optional[object] = None
_pipeline_model: str = ""
import threading as _threading
_pipeline_lock = _threading.Lock()


def _get_pipeline():
    """Lazy-load the HuggingFace NER pipeline (cached after first call)."""
    global _pipeline, _pipeline_model
    model_name = os.getenv("HF_NER_MODEL", "d4data/biomedical-ner-all")
    if _pipeline is None or _pipeline_model != model_name:
        import torch
        from transformers import pipeline as _hf_pipeline, AutoTokenizer, AutoModelForTokenClassification

        # Offline mode — use cached models, no network checks
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"]  = "1"

        # Load explicitly without device_map and without accelerate meta tensors.
        # device_map=None + low_cpu_mem_usage=False forces eager (non-meta) loading.
        tokenizer = AutoTokenizer.from_pretrained(
            model_name, local_files_only=True
        )
        model = AutoModelForTokenClassification.from_pretrained(
            model_name,
            device_map=None,           # never use accelerate's meta tensor path
            low_cpu_mem_usage=False,   # force full eager allocation
            local_files_only=True,
        )

        # Pick best available device
        if torch.cuda.is_available():
            device = 0
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = -1   # CPU

        new_pipeline = _hf_pipeline(
            "ner",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy="simple",
            device=device,
        )
        with _pipeline_lock:
            _pipeline = new_pipeline
            _pipeline_model = model_name
    return _pipeline


def should_run() -> bool:
    return os.getenv("HF_NER_ENABLED", "true").lower() == "true"


def tag_entities(text: str) -> list[dict]:
    """
    Run the HuggingFace NER model on text.
    Returns entity dicts in the same format as NERTagger.from_doc().
    Only entities with mapped labels (not OTHER) and score >= HF_NER_THRESHOLD
    are returned.
    """
    if not should_run():
        return []

    threshold = float(os.getenv("HF_NER_THRESHOLD", "0.80"))

    try:
        pipe    = _get_pipeline()
        results = pipe(text[:8000])   # cap at 8k chars to stay within context
    except Exception:
        return []

    entities = []
    seen     = set()

    for r in results:
        word  = r.get("word", "").strip()
        label = r.get("entity_group", "")
        score = float(r.get("score", 0.0))

        if not word or len(word) < 2:
            continue
        if score < threshold:
            continue

        # Map to our EntityType
        entity_type = HF_LABEL_MAP.get(label, "OTHER")
        if entity_type == "OTHER":
            continue   # skip unmapped / low-value labels

        # Clean BERT artefacts: ## prefixes from subword tokenisation
        word = word.replace(" ##", "").replace("##", "").strip()
        if not word:
            continue

        # Drop single-character fragments and very common short words
        if len(word) <= 2:
            continue
        if word.lower() in {"the", "a", "an", "of", "in", "to", "is", "are", "was",
                             "low", "high", "new", "old", "non", "pre", "pro", "anti"}:
            continue

        # Prefer offsets from HF pipeline — avoids always picking first occurrence.
        start = int(r.get("start", -1))
        end   = int(r.get("end", -1))
        if start >= 0 and end > start:
            word = text[start:end]  # exact span from original text, correct casing
        else:
            # Fallback: BERT hyphen normalization then text search
            word_norm = word.replace(" - ", "-").replace("- ", "-").replace(" -", "-")
            if word_norm.lower() not in text.lower() and word.lower() not in text.lower():
                continue
            if word_norm.lower() in text.lower():
                word = word_norm
            start = text.lower().find(word.lower())
            end   = start + len(word) if start >= 0 else -1

        # Verbatim check
        if word.lower() not in text.lower():
            continue

        # Dedup
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)

        entities.append({
            "text":       word,
            "normalized": key,
            "label":      entity_type,
            "start":      start,
            "end":        end,
            "negated":    False,
            "assertion":  "PRESENT",
            "confidence": round(score, 3),
            "source":     "hf_ner",
        })

    return entities
