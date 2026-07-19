#!/bin/bash
# ── Bio Semantic Parser — Docker Entrypoint ───────────────────────────────────
# Downloads NLP models on first startup if not already present.
# Models are cached in /root/.cache (mount from host to persist).

set -e

echo "=== Bio Semantic Parser starting ==="

# ── scispaCy models — pre-installed in Docker image, just verify ──────────────
for PKG in en_core_sci_lg en_ner_bc5cdr_md en_ner_jnlpba_md en_ner_bionlp13cg_md en_ner_craft_md; do
    python -c "import importlib; importlib.import_module('${PKG//-/_}')" 2>/dev/null \
        && echo "  ✓ ${PKG}" \
        || echo "  ✗ ${PKG} missing — image may need rebuild"
done

# ── HuggingFace models ────────────────────────────────────────────────────────
HF_CACHE="/root/.cache/huggingface"

_hf_ensure() {
    local model="$1"
    local label="$2"
    # HuggingFace cache folder: models--org--name (slashes → double-dash)
    local folder="${model//\//-}"
    folder="models--${folder//-/--}"
    # Simpler reliable check: try importing with local_files_only first
    if python -c "
from transformers import AutoTokenizer
AutoTokenizer.from_pretrained('${model}', local_files_only=True)
" 2>/dev/null; then
        echo "  ✓ ${label} cached"
    elif [ "${TRANSFORMERS_OFFLINE:-0}" = "1" ]; then
        echo "  ⚠ TRANSFORMERS_OFFLINE=1 but ${label} not cached — will fail at runtime"
    else
        echo "  ↓ Downloading ${label}..."
        python -c "
from transformers import AutoTokenizer, AutoModelForTokenClassification, AutoModelForSequenceClassification
try:
    AutoTokenizer.from_pretrained('${model}')
    AutoModelForTokenClassification.from_pretrained('${model}')
except Exception:
    AutoTokenizer.from_pretrained('${model}')
    AutoModelForSequenceClassification.from_pretrained('${model}')
"
        echo "  ✓ ${label} ready"
    fi
}

if [ "${HF_NER_ENABLED:-true}" = "true" ]; then
    _hf_ensure "${HF_NER_MODEL:-d4data/biomedical-ner-all}" "NER model (d4data/biomedical-ner-all)"
fi

_hf_ensure "cross-encoder/nli-MiniLM2-L6-H768" "Negation model (cross-encoder/nli-MiniLM2-L6-H768)"

echo "=== Models ready — starting server ==="
exec "$@"
