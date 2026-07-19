"""Pipeline checkpoint — save and restore layer outputs so a failed run can resume from any layer."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CHECKPOINT_ROOT = Path("data/checkpoints")

# Layers that produce saveable output
CHECKPOINTABLE_LAYERS = {3: "chunks", 4: "annotated", 6: "l6", 7: "processed", 8: "result"}
LAYER_NAMES = {
    3: "Universal Fetcher  (chunks)",
    4: "Pre-Extraction     (annotated chunks)",
    6: "Extraction Engine  (LLM results)",
    7: "Post-Extraction    (processed records)",
    8: "Publish            (output files + run_dir)",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ckpt_dir(doc_id: str) -> Path:
    safe = doc_id.replace("/", "_").replace(":", "_")[:64]
    return _CHECKPOINT_ROOT / safe


def _layer_file(doc_id: str, layer: int) -> Path:
    names = {3: "layer3_chunks", 4: "layer4_annotated",
             6: "layer6_results", 7: "layer7_processed",
             8: "layer8_result"}
    return _ckpt_dir(doc_id) / f"{names[layer]}.json"


def _meta_file(doc_id: str) -> Path:
    return _ckpt_dir(doc_id) / "meta.json"


# ── Save ──────────────────────────────────────────────────────────────────────

def fetch_paper_title(doc_id: str, source_name: str, url: str) -> str:
    """Fetch human-readable paper title via NCBI esummary (PMC/PubMed), CrossRef (PDF DOI), or filename fallback."""
    import re as _re
    try:
        import requests as _req

        # ── PMC ──────────────────────────────────────────────────────
        if source_name == "pmc" and doc_id.upper().startswith("PMC"):
            pmcid = doc_id.upper().replace("PMC", "")
            r = _req.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={"db": "pmc", "id": pmcid, "retmode": "json"},
                timeout=10,
            )
            title = r.json().get("result", {}).get(pmcid, {}).get("title", "")
            if title:
                return title[:120]

        # ── PubMed ───────────────────────────────────────────────────
        if source_name == "pubmed" and doc_id.isdigit():
            r = _req.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={"db": "pubmed", "id": doc_id, "retmode": "json"},
                timeout=10,
            )
            title = r.json().get("result", {}).get(doc_id, {}).get("title", "")
            if title:
                return title[:120]

        # ── ClinicalTrials ───────────────────────────────────────────
        if source_name == "clinicaltrials" and doc_id.startswith("NCT"):
            r = _req.get(
                f"https://clinicaltrials.gov/api/v2/studies/{doc_id}",
                params={"fields": "OfficialTitle,BriefTitle"},
                timeout=10,
            )
            data = r.json()
            title = (
                data.get("protocolSection", {})
                    .get("identificationModule", {})
                    .get("officialTitle")
                or data.get("protocolSection", {})
                    .get("identificationModule", {})
                    .get("briefTitle", "")
            )
            if title:
                return title[:120]

        # ── PDF — use filename (before .pdf), try DOI CrossRef for better title ──
        if source_name == "pdf":
            from pathlib import Path as _Path

            # Primary: filename stem (e.g. "hallmarks_aging.pdf" → "hallmarks_aging")
            fname_stem = _Path(url).stem if url else ""

            # Try CrossRef via DOI found in the paper
            ckpt_dir    = _ckpt_dir(doc_id)
            chunks_file = ckpt_dir / "layer3_chunks.json"
            if chunks_file.exists():
                try:
                    chunks    = json.loads(chunks_file.read_text(encoding="utf-8"))
                    full_text = " ".join(c.get("text", "") for c in chunks[:2])
                    doi_match = _re.search(r'10\.\d{4,}/\S+', full_text)
                    if doi_match:
                        found_doi = doi_match.group(0).rstrip('.,;)')
                        cr = _req.get(
                            f"https://api.crossref.org/works/{found_doi}",
                            timeout=8,
                            headers={"User-Agent": "bio-semantic-parser/1.0"},
                        )
                        cr_title = cr.json().get("message", {}).get("title", [""])[0]
                        if cr_title:
                            return cr_title[:120]
                except Exception:
                    pass

            # Fallback: filename stem as-is (user named it intentionally)
            return fname_stem[:80] if fname_stem else doc_id[:40]

    except Exception:
        pass

    # Fallback: short doc_id
    return doc_id[:40] if len(doc_id) > 40 else doc_id


def save_meta(doc_id: str, source_name: str, url: str) -> None:
    """Write/update the meta.json. Fetches and stores the paper title on first save."""
    path = _meta_file(doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {}
    if path.exists():
        try:
            meta = json.loads(path.read_text())
        except Exception:
            pass
    meta.update({
        "doc_id":      doc_id,
        "source_name": source_name,
        "url":         url,
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    })
    # Fetch title once (on first save or if missing)
    if not meta.get("paper_title"):
        meta["paper_title"] = fetch_paper_title(doc_id, source_name, url)
    path.write_text(json.dumps(meta, indent=2, default=str))


def get_paper_title(doc_id: str) -> str:
    """Return human-readable paper name: filename stem for PDFs, doc_id for database papers."""
    path = _meta_file(doc_id)
    if path.exists():
        try:
            meta = json.loads(path.read_text())
            src  = meta.get("source_name", "")
            url  = meta.get("url", "")
            if src == "pdf" and url:
                from pathlib import Path as _P
                return _P(url).stem   # "Cell.pdf" → "Cell"
            if src == "pdf":
                return meta.get("paper_title", "") or doc_id[:40]
            # Database paper: return the ID itself (PMC6746067, PMID, etc.)
            return doc_id
        except Exception:
            pass
    return doc_id[:40]


def save(doc_id: str, layer: int, data: Any) -> Path:
    """Serialise layer output to disk. Returns the path written."""
    path = _layer_file(doc_id, layer)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))
    _update_meta_layer(doc_id, layer)
    return path


def mark_complete(doc_id: str, layer: int) -> None:
    """Mark a layer as complete in meta.json without touching its data file."""
    try:
        _update_meta_layer(doc_id, layer)
    except Exception:
        pass


def _update_meta_layer(doc_id: str, layer: int) -> None:
    path = _meta_file(doc_id)
    meta = {}
    if path.exists():
        try:
            meta = json.loads(path.read_text())
        except Exception:
            pass
    completed = meta.get("completed_layers", [])
    if layer not in completed:
        completed.append(layer)
    meta["completed_layers"] = sorted(completed)
    meta["last_layer"] = max(completed)
    path.write_text(json.dumps(meta, indent=2, default=str))


# ── Load ──────────────────────────────────────────────────────────────────────

def load(doc_id: str, layer: int) -> Any | None:
    """Load a layer checkpoint. Returns None if it doesn't exist."""
    path = _layer_file(doc_id, layer)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ── Introspection ─────────────────────────────────────────────────────────────

def list_checkpoints() -> list[dict]:
    """Return all available checkpoints sorted by most-recently updated."""
    if not _CHECKPOINT_ROOT.exists():
        return []
    results = []
    for meta_path in sorted(_CHECKPOINT_ROOT.rglob("meta.json"),
                             key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(meta_path.read_text())
            results.append(meta)
        except Exception:
            pass
    return results


def completed_layers(doc_id: str) -> list[int]:
    """Return completed layers, cross-checking meta.json against actual files on disk."""
    from_meta: list = []
    path = _meta_file(doc_id)
    if path.exists():
        try:
            from_meta = json.loads(path.read_text()).get("completed_layers", [])
        except Exception:
            pass

    # Also scan actual layer files — layer is saved if its JSON file exists
    names_to_layer = {v: k for k, v in
                      {3: "layer3_chunks", 4: "layer4_annotated",
                       6: "layer6_results", 7: "layer7_processed",
                       8: "layer8_result"}.items()}
    from_files = [names_to_layer[f.stem]
                  for f in _ckpt_dir(doc_id).glob("layer*.json")
                  if f.stem in names_to_layer]

    merged = sorted(set(from_meta) | set(from_files))

    # Keep meta.json in sync if files were found that meta didn't record
    if from_files and set(from_files) - set(from_meta):
        try:
            meta = json.loads(path.read_text()) if path.exists() else {}
            meta["completed_layers"] = merged
            meta["last_layer"]       = max(merged) if merged else None
            path.write_text(json.dumps(meta, indent=2, default=str))
        except Exception:
            pass

    return merged


def resumable_from(doc_id: str) -> int | None:
    """Return the last completed layer (3→4→6→7 order), or None if no checkpoint exists."""
    order = [3, 4, 6, 7]
    done  = set(completed_layers(doc_id))
    if not done:
        return None
    # Find the last completed layer in order
    last = max((l for l in order if l in done), default=None)
    return last


def delete(doc_id: str) -> None:
    """Delete all checkpoints for this doc_id."""
    import shutil
    d = _ckpt_dir(doc_id)
    if d.exists():
        shutil.rmtree(d)
