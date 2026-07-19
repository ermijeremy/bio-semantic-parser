"""
Rich → WebSocket streaming bridge.

Captures Rich console output (panels, tables, rules, text) and emits
it as HTML fragments to the WebSocket stream, matching demo_showcase.py
output exactly — same colors, same panels, same tables.
"""
from io import StringIO
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich import box

# Layer colors matching demo_showcase.LAYER_COLORS
LAYER_COLORS = {
    1: "cyan", 2: "yellow", 3: "green",   4: "magenta",
    5: "blue", 6: "bright_blue", 7: "purple", 8: "bright_green",
}

# Layer descriptions matching demo_showcase.LAYER_DESCRIPTIONS exactly
LAYER_DESCRIPTIONS = {
    1: {
        "title": "Source Registry",
        "bullets": [
            "Loads all registered data sources from config/sources.yaml",
            "Each source defines: URL, format (XML/JSON/PDF), rate limit, ID field",
            "Adding a new source = add one YAML entry — zero code changes needed",
        ],
        "why": "The pipeline needs to know WHERE to fetch data and HOW to identify each document.",
    },
    2: {
        "title": "Scheduler",
        "bullets": [
            "Checks if this document was already processed — prevents duplicates",
            "Writes the document ID BEFORE fetching — if the pipeline crashes, no re-run duplicate",
            "Supports weekly auto-discovery if search_query is set in sources.yaml",
        ],
        "why": "Never process the same paper twice. Never write duplicate facts to the knowledge graph.",
    },
    3: {
        "title": "Universal Fetcher",
        "bullets": [
            "Step 1-2: Fetches raw bytes → detects format (XML/JSON/HTML/PDF) → extracts clean text",
            "Step 3: Noise removal — strips headers, footers, reference clutter",
            "Step 4: Coreference resolution — replaces 'it', 'they', 'this' with the actual entity names",
            "Step 5-6: Section splitting → chunking into context-window sized pieces with overlap",
            "Step 7: Metadata attachment — doc_id · source · section tag on every chunk",
        ],
        "why": "Converts ANY source format into identical structured chunks — downstream layers never need to know where data came from.",
    },
    4: {
        "title": "Pre-Extraction",
        "bullets": [
            "NER Ensemble: 3 scispaCy models identify diseases, genes, proteins, chemicals",
            "PubTator3 overlay: adds canonical MESH / NCBI Gene IDs to entities",
            "Negation detector: reads each sentence semantically — flags negative findings as negated=True",
            "DOI extractor: finds DOI → replaces SHA-256 hash with canonical paper ID",
            "Accession detector: finds GEO / ClinicalTrials / UniProt / SRA IDs",
        ],
        "why": "Gives the LLM pre-tagged entities with canonical IDs so it only needs to find relationships — not discover entities from scratch.",
    },
    5: {
        "title": "Schema",
        "bullets": [
            "87 canonical relation types from BioNLP · Hetionet · OpenBioLink · BioCypher · Biolink",
            "Each type has: definition · canonical example · 'not this' to avoid similar-type confusion",
            "13-field Pydantic model — wrong type or missing field = rejected immediately with specific error",
            "Instructor retry loop: Pydantic error fed back to LLM → up to 3 retries → rejected queue",
        ],
        "why": "A closed taxonomy makes the KG consistent — every paper uses the same vocabulary. Instructor forces the LLM to self-correct.",
    },
    6: {
        "title": "Extraction Engine",
        "bullets": [
            "Calls local Gemma 4 LLM for each chunk with full taxonomy + pre-tagged entities",
            "LLM fills 13 fields: extraction_viable FIRST → subject → relation → object → context",
            "Pydantic validates every output field — wrong relation type = rejected",
            "On rejection: specific error fed back to LLM → retry → rejected queue after 3 failures",
        ],
        "why": "The LLM focuses only on finding the relationship — entities are already identified by Layer 4. Division of labour makes extraction more accurate.",
    },
    7: {
        "title": "Post-Extraction",
        "bullets": [
            "Step 1: Entity Normalization → MESH / NCBI Gene / ChEBI canonical IDs",
            "Step 2: Deduplication → same triple from another paper? update confidence",
            "Step 3: Contradiction detection → inhibits vs activates for same pair? flag both",
            "Step 4: Cross-chunk linking → relations sharing entities within same paper linked",
            "Step 5: Two-pass resolution → second LLM call for unresolved entity IDs",
            "Step 6: Semantic validation → second independent LLM verifies against source text",
            "Step 7: Atomspace alignment → ID in KG? connect. New? create node",
        ],
        "why": "Seven quality gates before anything reaches the knowledge graph. Each gate catches a different type of error.",
    },
    8: {
        "title": "Publish",
        "bullets": [
            "Validation gate: confidence ≥ 0.85 AND no flags → auto-insert",
            "Below threshold OR any flag → human review queue (JSONL + CSV)",
            "Auto-insert → Neo4j CSV (nodes_{type}.csv + edges_{src}_{rel}_{tgt}.csv + .cypher)",
            "Auto-insert → MeTTa ((relation (src_type ID) (tgt_type ID)) + stv + source)",
            "One atomic write function — both paths — never out of sync",
        ],
        "why": "Final routing decision. Wrong facts go to human review. Confident validated facts enter the knowledge graph immediately.",
    },
}


def _make_console(width: int = 200) -> Console:
    """Return a Rich console that records output as HTML.
    Width 200 ensures tables don't wrap — the browser scrolls horizontally if needed.
    """
    return Console(record=True, force_terminal=False, width=width,
                   highlight=False, markup=True)


class _AutoPrompt:
    """Returns the default value immediately — replaces rich.prompt.Prompt."""
    @staticmethod
    def ask(prompt: str = "", choices=None, default=None, **_kw):
        return default if default is not None else (choices[0] if choices else "y")


class _AutoConfirm:
    """Returns the default value immediately — replaces rich.prompt.Confirm."""
    @staticmethod
    def ask(prompt: str = "", default: bool = True, **_kw):
        return default


def capture_demo_output(fn, *args, emit: Callable, layer: int, **kwargs):
    """
    Run a demo_pipeline show_layer* function with a recording console,
    auto-answering all Prompt/Confirm with their defaults (no waiting),
    then stream the captured HTML to the WebSocket.
    """
    import tests.demo_pipeline as _dp
    import rich.prompt as _rp
    import re as _re

    _orig_console      = _dp.console
    _orig_rp_prompt    = _rp.Prompt
    _orig_rp_confirm   = _rp.Confirm
    _orig_dp_prompt    = getattr(_dp, 'Prompt',  None)
    _orig_dp_confirm   = getattr(_dp, 'Confirm', None)
    rec_console = _make_console()

    # Patch both the module-level binding AND demo_pipeline's local name
    _dp.console = rec_console
    _rp.Prompt  = _AutoPrompt   # type: ignore
    _rp.Confirm = _AutoConfirm  # type: ignore
    _dp.Prompt  = _AutoPrompt   # type: ignore
    _dp.Confirm = _AutoConfirm  # type: ignore

    try:
        result = fn(*args, **kwargs)
    finally:
        _dp.console = _orig_console
        _rp.Prompt  = _orig_rp_prompt
        _rp.Confirm = _orig_rp_confirm
        if _orig_dp_prompt  is not None: _dp.Prompt  = _orig_dp_prompt
        if _orig_dp_confirm is not None: _dp.Confirm = _orig_dp_confirm

    html = rec_console.export_html(inline_styles=True)
    body = _re.search(r'<pre[^>]*>(.*?)</pre>', html, _re.DOTALL)
    if body and body.group(1).strip():
        emit({"layer": layer, "status": "log",
              "message": body.group(1), "data": {"kind": "html"}})
    return result


def _flush(console: Console, emit: Callable, layer: int) -> None:
    """Export recorded Rich output as HTML and emit it."""
    html = console.export_html(inline_styles=True, theme=None)
    # Extract just the <pre> body — strip full HTML boilerplate
    import re
    body = re.search(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL)
    if body:
        content = body.group(1)
        emit({"layer": layer, "status": "log",
              "message": content, "data": {"kind": "html"}})


def emit_pre_layer(layer: int, emit: Callable) -> None:
    """Emit the LAYER N pre-panel exactly as demo_showcase._pre_layer()."""
    desc  = LAYER_DESCRIPTIONS.get(layer, {})
    color = LAYER_COLORS.get(layer, "white")
    bullets = desc.get("bullets", [])
    why     = desc.get("why", "")
    title   = desc.get("title", f"Layer {layer}")

    console = _make_console()
    bullet_text = "\n".join(
        f"  [bold {color}]•[/bold {color}] {b}" for b in bullets
    )
    why_text = f"\n\n  [dim]Why it exists:[/dim] {why}"
    console.print(Panel(
        bullet_text + why_text,
        title=f"[bold {color}]LAYER {layer} — {title.upper()}[/bold {color}]",
        border_style=color, padding=(0, 2),
    ))
    console.print()
    _flush(console, emit, layer)


def emit_post_layer(layer: int, items: list, emit: Callable) -> None:
    """Emit the WHAT WE FOUND panel exactly as demo_showcase._post_layer()."""
    color = LAYER_COLORS.get(layer, "green")
    content = "\n".join(f"  [{color}]✓[/{color}]  {item}" for item in items)
    console = _make_console()
    console.print(Panel(
        content,
        title="[bold]WHAT WE FOUND[/bold]",
        border_style=color, padding=(0, 2),
    ))
    console.print()
    _flush(console, emit, layer)


def emit_rule(layer: int, title: str, emit: Callable, color: str = None) -> None:
    """Emit a horizontal rule separator."""
    c = color or LAYER_COLORS.get(layer, "dim")
    console = _make_console()
    console.print(Rule(f"[bold {c}]  {title}  [/bold {c}]", style=c))
    _flush(console, emit, layer)


def emit_table(layer: int, headers: list, rows: list, emit: Callable,
               title: str = "", color: str = None) -> None:
    """Emit a Rich table."""
    c = color or LAYER_COLORS.get(layer, "white")
    console = _make_console()
    t = Table(box=box.SIMPLE, show_header=bool(headers),
              header_style=f"bold {c}", padding=(0, 1),
              title=f"[bold {c}]{title}[/bold {c}]" if title else None)
    for h in headers:
        t.add_column(h)
    for row in rows:
        t.add_row(*[str(x) for x in row])
    console.print(t)
    _flush(console, emit, layer)


def emit_text(layer: int, text: str, emit: Callable) -> None:
    """Emit arbitrary Rich markup text."""
    console = _make_console()
    console.print(text)
    _flush(console, emit, layer)
