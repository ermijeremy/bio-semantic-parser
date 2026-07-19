"""Shared helpers used by pipeline_runner and each layer module."""
import os
import sys
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_preextractor = None  # lazy-loaded NER singleton


def warm_models() -> None:
    """Pre-load NER models at startup so the first pipeline run isn't slow."""
    global _preextractor
    if _preextractor is None:
        from src.preextraction.preextractor import Preextractor
        _preextractor = Preextractor()


def _emit(cb: Callable, layer: int, status: str, message: str = "", data: dict = None):
    cb({"layer": layer, "status": status, "message": message, "data": data or {}})


def _log(emit, layer, msg, kind=""):
    emit({"layer": layer, "status": "log", "message": msg, "data": {"kind": kind}})


def _pre(emit, layer):
    from api.rich_stream import emit_pre_layer
    emit_pre_layer(layer, emit)


def _post(emit, layer, items):
    from api.rich_stream import emit_post_layer
    emit_post_layer(layer, items, emit)


def _ckpt(doc_id: str, layer: int):
    try:
        from src.pipeline_checkpoint import mark_complete as _mark_complete
        _mark_complete(doc_id, layer)
    except Exception:
        pass


def _rule(emit, layer, title):
    from api.rich_stream import emit_rule
    emit_rule(layer, title, emit)


def _rtable(emit, layer, headers, rows, title=""):
    from api.rich_stream import emit_table
    emit_table(layer, headers, rows, emit, title=title)


def _rtext(emit, layer, text):
    from api.rich_stream import emit_text
    emit_text(layer, text, emit)


LAYER_DESC = {
    1: {
        "bullets": [
            "Loads all registered data sources from config/sources.yaml",
            "Each source defines: URL, format (XML/JSON/PDF), rate limit, ID field",
            "Adding a new source = add one YAML entry — zero code changes needed",
        ],
        "why": "The pipeline needs to know WHERE to fetch data and HOW to identify each document.",
    },
    2: {
        "bullets": [
            "Checks if this document was already processed — prevents duplicates",
            "Writes the document ID BEFORE fetching — if pipeline crashes, no re-run duplicate",
        ],
        "why": "Never process the same paper twice. Never write duplicate facts to the knowledge graph.",
    },
    3: {
        "bullets": [
            "Step 1-2: Fetches raw bytes → detects format (XML/JSON/HTML/PDF) → extracts clean text",
            "Step 3: Noise removal — strips headers, footers, reference clutter",
            "Step 4: Coreference resolution — replaces 'it', 'they', 'this' with actual entity names",
            "Step 5-6: Section splitting → chunking into context-window sized pieces",
            "Step 7: Metadata attachment — doc_id · source · section tag on every chunk",
        ],
        "why": "Converts ANY source format into identical structured chunks — downstream layers never need to know where data came from.",
    },
    4: {
        "bullets": [
            "NER Ensemble: 4 scispaCy models + HuggingFace clinical NER — diseases, genes, proteins, chemicals, procedures, drugs, clinical interventions",
            "PubTator3 overlay: adds canonical MESH / NCBI Gene IDs to entities",
            "Negation detector: reads each sentence semantically — flags negative findings",
            "DOI extractor: finds DOI → replaces SHA-256 hash with canonical paper ID",
            "Accession detector: finds GEO / ClinicalTrials / UniProt / SRA IDs",
        ],
        "why": "Gives the LLM pre-tagged entities with canonical IDs so it only needs to find relationships — not discover entities from scratch.",
    },
    5: {
        "bullets": [
            "87 canonical relation types from BioNLP · Hetionet · OpenBioLink · BioCypher · Biolink",
            "Each type has: definition · example · 'not this' to avoid confusion",
            "13-field Pydantic model — wrong type or missing field = rejected immediately",
            "Instructor retry loop: Pydantic error fed back to LLM → up to 3 retries → rejected queue",
        ],
        "why": "A closed taxonomy makes the KG consistent — every paper uses the same vocabulary.",
    },
    6: {
        "bullets": [
            "Calls local Gemma 4 LLM for each chunk with full taxonomy + pre-tagged entities",
            "LLM fills 13 fields: extraction_viable FIRST → subject → relation → object → context",
            "Pydantic validates every output field — wrong relation type = rejected",
            "On rejection: specific error fed back to LLM → retry → rejected queue after 3 failures",
        ],
        "why": "The LLM focuses only on finding relationships — entities are already identified by Layer 4.",
    },
    7: {
        "bullets": [
            "Step 1: Entity Normalization → MESH / NCBI Gene / ChEBI canonical IDs",
            "Step 2: Deduplication → same triple from another paper? update confidence",
            "Step 3: Contradiction detection → inhibits vs activates? flag both",
            "Step 4: Cross-chunk linking → relations sharing entities within paper",
            "Step 5: Two-pass resolution → second LLM call for unresolved entity IDs",
            "Step 6: Semantic validation → second independent LLM verifies against source text",
            "Step 7: Atomspace alignment → ID in KG? connect. New? create node",
        ],
        "why": "Seven quality gates before anything reaches the knowledge graph.",
    },
    8: {
        "bullets": [
            "Validation gate: Semantic verdict VALID → auto-insert (no confidence threshold)",
            "Below threshold OR any flag → human review queue (JSONL + CSV)",
            "Auto-insert → Neo4j CSV (nodes_{type}.csv + edges_{src}_{rel}_{tgt}.csv + .cypher)",
            "Auto-insert → MeTTa ((relation (src_type ID) (tgt_type ID)) + stv + source)",
        ],
        "why": "Final routing decision. Wrong facts go to human review. Confident validated facts enter the knowledge graph immediately.",
    },
}


def _load_ver_stats(ver_json_path, fallback_total=0):
    """Load verified/total/pct from verification_report.json — never show 0/N."""
    try:
        import json as _jj
        recs      = _jj.loads(ver_json_path.read_text())
        confirmed = sum(1 for r in recs if r.get("overall_status") == "CONFIRMED")
        total     = len(recs)
        pct       = confirmed * 100 // total if total else 0
        return {"verified": confirmed, "total": total or fallback_total,
                "ver_pct": pct, "ver_results": recs[:35]}
    except Exception:
        return {"verified": 0, "total": fallback_total, "ver_pct": 0, "ver_results": []}


def _count_run_edges(run_dir, fmt="neo4j"):
    """Count edges from the run's output files — respects format selection."""
    try:
        count = 0
        if fmt in ("neo4j", "both"):
            for csv in (run_dir / "neo4j").rglob("edges_*.csv"):
                with open(csv) as f:
                    count += max(0, sum(1 for _ in f) - 1)
        elif fmt == "metta":
            for metta in (run_dir / "metta").rglob("edges_*.metta"):
                with open(metta) as f:
                    count += sum(1 for l in f
                                 if l.strip() and not l.strip().startswith(';')
                                 and not l.strip().startswith('(stv ')
                                 and not l.strip().startswith('(negated')
                                 and not l.strip().startswith('(source')
                                 and not l.strip().startswith('(reasoning')
                                 and not l.strip().startswith('(species'))
        return count
    except Exception:
        return 0


def _resolve_input(input_type, input_value, source_name, all_sources, scheduler):
    """Return (source_dict, doc_id, fetch_url)."""
    import hashlib, re
    src_map = {s["name"]: s for s in all_sources}

    if input_type == "pdf":
        src = {"name": "pdf", "type": "file", "format": "pdf",
               "base_url": None, "id_field": None}
        return src, Path(input_value).stem, str(input_value)

    if source_name and source_name in src_map:
        src    = src_map[source_name]
        doc_id = input_value.strip()
        url    = scheduler._build_fetch_url(src, doc_id)
        return src, doc_id, url

    val = input_value.strip()
    if val.upper().startswith("PMC") and val[3:].isdigit():
        src = src_map.get("pmc", all_sources[0])
        return src, val.upper(), scheduler._build_fetch_url(src, val.upper())
    if val.isdigit():
        src = src_map.get("pubmed", all_sources[0])
        return src, val, scheduler._build_fetch_url(src, val)

    pmc = re.search(r'PMC(\d+)', val, re.I)
    if pmc:
        src    = src_map.get("pmc", all_sources[0])
        doc_id = "PMC" + pmc.group(1)
        return src, doc_id, scheduler._build_fetch_url(src, doc_id)

    pm = re.search(r'pubmed[^\d]*(\d+)', val, re.I)
    if pm:
        src = src_map.get("pubmed", all_sources[0])
        return src, pm.group(1), scheduler._build_fetch_url(src, pm.group(1))

    pmid_url = re.search(r'nlm\.nih\.gov/(\d{6,9})/?', val)
    if pmid_url:
        src = src_map.get("pubmed", all_sources[0])
        return src, pmid_url.group(1), scheduler._build_fetch_url(src, pmid_url.group(1))

    if val.startswith("http") or val.startswith("10."):
        src    = src_map.get("pmc", all_sources[0])
        doc_id = hashlib.sha256(val.encode()).hexdigest()[:16]
        return src, doc_id, val

    _upload_candidate = Path("data/uploads") / f"{val}.pdf"
    if _upload_candidate.exists():
        src = {"name": "pdf", "type": "file", "format": "pdf",
               "base_url": None, "id_field": None}
        return src, val, str(_upload_candidate)

    src    = src_map.get(input_type, all_sources[0])
    doc_id = hashlib.sha256(val.encode()).hexdigest()
    return src, doc_id, val
