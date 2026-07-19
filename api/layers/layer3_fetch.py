"""Layer 3 — Fetch, parse, clean, coref-resolve and chunk the paper."""
import os
from pathlib import Path
from api.pipeline_utils import _emit, _log, _pre, _post, _ckpt


def run_layer3(emit, doc_id, _safe_id, fetch_url, source, paper_url, _completed_layers):
    """Fetch the paper and return (chunks, title), or None on error.

    Loads from checkpoint if Layer 3 is already complete.
    """
    def _skip(layer): return layer in _completed_layers

    title    = _get_paper_title(doc_id) or doc_id
    _l3_saved = Path(f"data/checkpoints/{_safe_id}/layer3_chunks.json")

    _pre(emit, 3)

    if _skip(3) and _l3_saved.exists():
        try:
            import json as _jj3l
            _saved = _jj3l.loads(_l3_saved.read_text())
            if _saved and isinstance(_saved, list):
                _emit(emit, 3, "done",
                      f"Checkpoint — {len(_saved)} chunks loaded, fetch skipped ✓",
                      {"chunks": len(_saved)})
                return _saved, title
        except Exception:
            pass  # fall through to re-fetch

    _emit(emit, 3, "running", "Fetching and parsing paper…")
    try:
        coref_url = os.getenv("COREF_SERVICE_URL", "http://202.181.159.222:8081")
        from src.fetcher.fetcher import Fetcher
        fetcher = Fetcher(coref_url=coref_url)

        def _render_coref_html(msg):
            try:
                from api.rich_stream import _make_console
                from tests.demo_pipeline import render_before, render_after, extract_changes
                import re as _re2
                parts          = msg[len("__COREF__"):]
                idx_part, rest = parts.split("__", 1)
                before, after  = rest.split("__||__", 1)
                idx, total     = idx_part.split("/")
                _c = _make_console()
                _c.print(f"   [dim]{'─' * 72}[/dim]")
                _c.print(f"   [dim bold][{idx}/{total}][/dim bold]")
                _c.print(f"   [red]BEFORE[/red] ", end="")
                _c.print(render_before(before, after))
                _c.print(f"   [green]AFTER [/green] ", end="")
                _c.print(render_after(before, after))
                for removed, added in extract_changes(before, after):
                    if removed == "∅":
                        _c.print(f"          [dim]＋ inserted:[/dim] [bold green]\"{added}\"[/bold green]")
                    elif added == "∅":
                        _c.print(f"          [dim]－ removed:[/dim]  [bold red]\"{removed}\"[/bold red]")
                    else:
                        _c.print(f"          [dim]↳ replaced:[/dim] [bold red]\"{removed}\"[/bold red] [dim]→[/dim] [bold green]\"{added}\"[/bold green]")
                _c.print()
                html = _c.export_html(inline_styles=True)
                body = _re2.search(r'<pre[^>]*>(.*?)</pre>', html, _re2.DOTALL)
                if body:
                    emit({"layer": 3, "status": "log", "message": body.group(1), "data": {"kind": "html"}})
            except Exception:
                pass

        def _l3_log(msg):
            m    = msg.strip()
            if m.startswith("__COREF__"):
                _render_coref_html(m)
                return
            kind = "step" if m.lower().startswith("step ") else "ok" if "✓" in m else ""
            _log(emit, 3, m, kind)

        chunks = fetcher.fetch(fetch_url, source, doc_id, paper_url=paper_url, log_cb=_l3_log)
        title  = _get_paper_title(doc_id) or doc_id

        from api.rich_stream import _make_console
        import re as _re_l3
        for i, c in enumerate(chunks, 1):
            tokens = len(c.get('text', '').split())
            _c     = _make_console()
            from rich.panel import Panel as _P
            _c.print(_P(
                c.get('text', ''),
                title=(f"[bold yellow] Chunk {i}/{len(chunks)} [/bold yellow]"
                       f"[dim]  section={c.get('section', '?')}  words≈{tokens}[/dim]"),
                border_style="yellow", padding=(0, 2),
            ))
            html = _c.export_html(inline_styles=True)
            body = _re_l3.search(r'<pre[^>]*>(.*?)</pre>', html, _re_l3.DOTALL)
            if body:
                emit({"layer": 3, "status": "log", "message": body.group(1), "data": {"kind": "html"}})

        _emit(emit, 3, "done", f"'{title}' — {len(chunks)} chunks", {
            "doc_id":   doc_id,
            "title":    title,
            "chunks":   len(chunks),
            "sections": list({c.get("section", "unknown") for c in chunks}),
        })
        _post(emit, 3, [
            f"{len(chunks)} chunk(s) extracted from '{title}'",
            f"Sections found: {', '.join(sorted({c.get('section', '?') for c in chunks}))}",
            "Coreference resolution applied — pronouns replaced with entity names",
            "Metadata attached: doc_id · source · section tag on every chunk",
        ])
        try:
            import json as _jj3
            _c3dir = Path(f"data/checkpoints/{_safe_id}")
            _c3dir.mkdir(parents=True, exist_ok=True)
            (_c3dir / "layer3_chunks.json").write_text(
                _jj3.dumps(chunks, default=str), encoding="utf-8"
            )
        except Exception:
            pass
        _ckpt(doc_id, 3)
        return chunks, title
    except Exception as e:
        _emit(emit, 3, "error", str(e))
        return None


def _get_paper_title(doc_id):
    try:
        from src.pipeline_checkpoint import get_paper_title
        return get_paper_title(doc_id)
    except Exception:
        return None
