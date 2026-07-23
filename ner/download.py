"""Prefetch model weights into the local cache (ner/models/_hf_cache).

Downloads each selected model's HuggingFace snapshot ONCE so later loads are
fully offline and fast. Run before benchmarking so the first UI interaction
isn't a multi-GB download.

    python -m ner.download                 # all HuggingFace-hub models
    python -m ner.download gliner_biomed_large biobert_genetic
    python -m ner.download --list          # show keys and download state

Non-hub models (scispaCy pip packages, Stanza) are noted but skipped — install
those via pip / their own downloader.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from . import cache

cache.configure(offline=False)  # must be online to fetch

from .models import REGISTRY  # noqa: E402

# Registry key -> HuggingFace repo id to snapshot. Models not here use a
# different distribution channel (pip package / Stanza resources).
HF_REPOS = {
    "gliner_biomed_large": "Ihor/gliner-biomed-large-v1.0",
    "gliner_biomed_base": "Ihor/gliner-biomed-base-v1.0",
    "gliner_biomed_bi_large": "Ihor/gliner-biomed-bi-large-v1.0",
    "biomedical_ner_all": "d4data/biomedical-ner-all",
    "hunflair2": "hunflair/hunflair2-ner",
    "bent_gene": "pruas/BENT-PubMedBERT-NER-Gene",
    "bent_disease": "pruas/BENT-PubMedBERT-NER-Disease",
    "pubmedbert_protein_structure": "PDBEurope/BiomedNLP-PubMedBERT-ProteinStructure-NER-v3.1",
    "biobert_diseases": "alvaroalon2/biobert_diseases_ner",
    "biobert_chemical": "alvaroalon2/biobert_chemical_ner",
    "biobert_genetic": "alvaroalon2/biobert_genetic_ner",
}

# Keys distributed outside the HF hub snapshot flow.
NON_HUB = {
    "scispacy_ensemble": "pip install the en_ner_*_md scispaCy wheels (see requirements.txt)",
    "stanza_bionlp13cg": "downloaded automatically by Stanza on first load",
}


def _is_downloaded(repo_id: str) -> bool:
    from huggingface_hub import try_to_load_from_cache
    from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE
    # A config.json resolving to a real path means the snapshot exists.
    for fname in ("config.json", "gliner_config.json"):
        hit = try_to_load_from_cache(repo_id, fname, cache_dir=HUGGINGFACE_HUB_CACHE)
        if isinstance(hit, str):
            return True
    return False


def list_state() -> None:
    print(f"Local cache: {cache.LOCAL_HUB}\n")
    for key in REGISTRY:
        if key in HF_REPOS:
            state = "cached" if _is_downloaded(HF_REPOS[key]) else "NOT downloaded"
            print(f"  {key:32s} {HF_REPOS[key]:52s} [{state}]")
        else:
            print(f"  {key:32s} {'(non-hub)':52s} [{NON_HUB.get(key, 'n/a')}]")


def migrate_from_home() -> None:
    """Move already-downloaded model dirs from ~/.cache/huggingface into the
    local cache — no network, avoids re-downloading what you already have.

    Only migrates models that have real weight files; skips config-only
    (never-finished) downloads so they get a clean fetch instead.
    """
    import shutil

    home_hub = Path.home() / ".cache" / "huggingface" / "hub"
    if not home_hub.is_dir():
        print("No home cache to migrate from.")
        return
    cache.LOCAL_HUB.mkdir(parents=True, exist_ok=True)

    wanted = {repo.replace("/", "--") for repo in HF_REPOS.values()}
    moved = 0
    for src in home_hub.glob("models--*"):
        if src.name.replace("models--", "") not in wanted:
            continue
        has_weights = any(src.glob("snapshots/*/*.safetensors")) or any(src.glob("snapshots/*/*.bin"))
        dst = cache.LOCAL_HUB / src.name
        if not has_weights:
            print(f"⏭  {src.name}: no weight files (will re-download on demand)")
            continue
        if dst.exists():
            print(f"✓  {src.name}: already in local cache")
            continue
        print(f"→  moving {src.name} …", flush=True)
        shutil.move(str(src), str(dst))
        moved += 1
    print(f"\nMigrated {moved} model(s) into {cache.LOCAL_HUB}")


def download(keys: list[str]) -> None:
    from huggingface_hub import snapshot_download

    removed = cache.clean_incomplete()
    if removed:
        print(f"Cleaned {removed} incomplete download(s).\n")

    targets = [k for k in keys if k in HF_REPOS]
    skipped = [k for k in keys if k in NON_HUB]

    for key in skipped:
        print(f"⏭  {key}: {NON_HUB[key]}")

    for i, key in enumerate(targets, 1):
        repo = HF_REPOS[key]
        print(f"[{i}/{len(targets)}] {key} — {repo} …", flush=True)
        t = time.perf_counter()
        try:
            snapshot_download(
                repo_id=repo,
                cache_dir=str(cache.LOCAL_HUB),
                # Skip redundant weight formats to save space/time.
                ignore_patterns=["*.h5", "*.tflite", "*.msgpack", "*.onnx", "rng_state*", "optimizer*", "scheduler*", "trainer_state*"],
            )
            print(f"      done in {time.perf_counter() - t:.1f}s")
        except Exception as e:
            print(f"      FAILED: {type(e).__name__}: {e}")

    print("\nDone. Loads will now run offline from", cache.LOCAL_HUB)


def main(argv: list[str]) -> None:
    if "--list" in argv or "-l" in argv:
        list_state()
        return
    if "--migrate" in argv:
        migrate_from_home()
        if argv == ["--migrate"]:
            return
    keys = [a for a in argv if not a.startswith("-")]
    if not keys:
        keys = list(HF_REPOS)  # all hub models
    unknown = [k for k in keys if k not in REGISTRY]
    if unknown:
        print("Unknown model key(s):", ", ".join(unknown))
        print("Valid keys:", ", ".join(REGISTRY))
        sys.exit(1)
    download(keys)


if __name__ == "__main__":
    main(sys.argv[1:])
