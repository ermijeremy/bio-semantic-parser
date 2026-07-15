"""Centralised local model-cache configuration.

Import this module ONCE at the top of any model file (or from _hf_pipeline.py)
before importing torch / transformers / gliner / flair / stanza.  It redirects
every library's weight-cache to  ner/models/_hf_cache/  so that:

  • Models download exactly once into the repo tree (not ~/.cache/…).
  • Subsequent process starts skip the network entirely.
  • CI / Docker builds can pre-populate the cache and bake it into an image.

The env-vars are set at import time so that later ``from transformers import …``
calls already see the correct paths.
"""
from __future__ import annotations

import os
from pathlib import Path

# Absolute path of ner/models/_hf_cache regardless of cwd.
_MODELS_DIR = Path(__file__).parent
CACHE_DIR   = _MODELS_DIR / "_hf_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── HuggingFace (transformers, GLiNER, huggingface_hub) ──────────────────────
# HF_HOME is the top-level umbrella; HF_HUB_CACHE is the legacy override kept
# for compatibility with older huggingface_hub versions.
_hf = str(CACHE_DIR)
os.environ.setdefault("HF_HOME",            _hf)
os.environ.setdefault("HF_HUB_CACHE",       str(CACHE_DIR / "hub"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE_DIR / "hub"))

# ── Stanza ───────────────────────────────────────────────────────────────────
os.environ.setdefault("STANZA_RESOURCES_DIR", str(CACHE_DIR / "stanza"))

# ── Flair ────────────────────────────────────────────────────────────────────
os.environ.setdefault("FLAIR_CACHE_ROOT", str(CACHE_DIR / "flair"))

# ── Torch hub (used by some Flair sub-models) ────────────────────────────────
os.environ.setdefault("TORCH_HOME", str(CACHE_DIR / "torch"))

# ── Disable progress bars when running in a non-TTY (e.g. benchmarks) ───────
if not os.isatty(1):
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
