"""Local model cache configuration.

Points all HuggingFace downloads at ``ner/models/_hf_cache`` so weights are
stored *inside* the package (downloaded once, reused forever) instead of the
user's home cache, and enables offline mode once models are present so loads
stop hitting the network to revalidate every file.

This must run before ``huggingface_hub`` / ``transformers`` / ``gliner`` are
imported — it is invoked from ``ner/__init__.py`` for exactly that reason.
"""
from __future__ import annotations

import os
from pathlib import Path

# Weights live here, next to the model code. Override with NER_HF_CACHE.
LOCAL_CACHE = Path(
    os.environ.get("NER_HF_CACHE", str(Path(__file__).resolve().parent / "models" / "_hf_cache"))
)
LOCAL_HUB = LOCAL_CACHE / "hub"


def _hub_has_snapshots() -> bool:
    """True if at least one model has been downloaded into the local hub."""
    if not LOCAL_HUB.is_dir():
        return False
    return any(LOCAL_HUB.glob("models--*/snapshots/*"))


def configure(offline: bool | None = None) -> Path:
    """Set HF cache env vars (idempotent). Returns the local cache dir.

    ``offline`` resolution (fastest safe default):
      * NER_OFFLINE=1 / true  -> force offline (skip all network revalidation)
      * NER_OFFLINE=0 / false -> force online
      * unset ("auto")        -> offline iff something is already downloaded
    """
    LOCAL_HUB.mkdir(parents=True, exist_ok=True)

    os.environ["HF_HOME"] = str(LOCAL_CACHE)
    os.environ["HF_HUB_CACHE"] = str(LOCAL_HUB)
    # Silence the tokenizers fork warning that can also stall on some systems.
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    if offline is None:
        flag = os.environ.get("NER_OFFLINE", "auto").lower()
        if flag in ("1", "true", "yes", "on"):
            offline = True
        elif flag in ("0", "false", "no", "off"):
            offline = False
        else:  # auto
            offline = _hub_has_snapshots()

    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)

    return LOCAL_CACHE


def clean_incomplete() -> int:
    """Delete partial (`*.incomplete`) downloads that force re-downloads.

    Also scans the legacy ~/.cache/huggingface hub. Returns count removed.
    """
    removed = 0
    roots = [LOCAL_HUB, Path.home() / ".cache" / "huggingface" / "hub"]
    for root in roots:
        if not root.is_dir():
            continue
        for f in root.rglob("*.incomplete"):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed
