"""BioNER model comparison harness.

Isolated implementations of biomedical NER models behind a common interface,
plus a shared gold corpus, evaluation harness, and a Flask comparison UI.

Run the dashboard from the repo root:

    python -m ner.app
"""
# Point all HuggingFace downloads at ner/models/_hf_cache and enable offline
# mode once models are present. Must happen before transformers/gliner import.
from . import cache as _cache

_cache.configure()

