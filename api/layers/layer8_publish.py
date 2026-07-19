"""Layer 8 — Publish to knowledge graph, inline verification, deep verification."""
import os
from pathlib import Path
from api.pipeline_utils import _emit, _log, _pre, _post, _ckpt, _rtext, _count_run_edges


def run_layer8(emit, doc_id, _safe_id, processed, tagged_chunks, staging_db,
               output_format, title):
    """Write validated triples to the KG, run verification, generate graph HTML."""
    _pre(emit, 8)
    _emit(emit, 8, "running", "Writing to knowledge graph…")
    try:
        from collections import defaultdict
        from src.publish.output_layer import process as pub_process
        _by_doc = defaultdict(list)
        for c in tagged_chunks:
            if c.get("text"): _by_doc[c.get("document_id", "")].append(c["text"])
        text_by_doc = {k: " ".join(v) for k, v in _by_doc.items()}

        pub     = pub_process(processed, verbose=False, text_by_doc=text_by_doc,
                              formats=output_format, paper_name=title, doc_id=doc_id)
        os.environ.pop("TRIPLE_STORE_PATH", None)
        run_dir = Path(pub.get("run_dir", ""))
        neo4j   = pub.get("neo4j", {})
        metta   = pub.get("metta", {})
        verif   = pub.get("verification", {})
        v_total = verif.get("total", 0)
        v_ok    = verif.get("verified", 0)
        v_bad   = verif.get("mismatched", 0)
        ver_pct = int(v_ok * 100 / v_total) if v_total else 0

        post_bullets = [
            f"{pub.get('auto_insert', 0)} relation(s) auto-inserted (semantic verdict VALID)",
            f"{pub.get('human_review', 0)} to human review queue → data/kg_output/human_review.jsonl",
        ]
        if output_format in ("neo4j", "both"):
            post_bullets.append(f"Neo4j: {neo4j.get('node_count', 0)} nodes  {neo4j.get('edge_count', 0)} edges")
        if output_format in ("metta", "both"):
            post_bullets.append(f"MeTTa: {metta.get('node_count', 0)} nodes  {metta.get('edge_count', 0)} edges")
        _post(emit, 8, post_bullets)

        if v_total > 0:
            from rich.console import Console as _Con
            from rich.table import Table as _Tab
            from rich import box as _box
            pct_color = "bright_green" if ver_pct >= 90 else ("yellow" if ver_pct >= 70 else "red")
            filled    = round(ver_pct / 10)
            bar       = f"[{pct_color}]{'█' * filled}[/{pct_color}][dim]{'░' * (10 - filled)}[/dim]"
            _con = _Con(record=True, force_terminal=False, width=120)
            from rich.panel import Panel as _Panel
            _con.print(_Panel(
                f"  {bar}  [{pct_color}][bold]{ver_pct}%[/bold][/{pct_color}] confirmed against source text\n"
                f"  [green]✓ Verified[/green]   {v_ok}   of {v_total} relations found in paper text\n"
                f"  [red]✗ Mismatch[/red]   {v_bad}  relation(s) not confirmed",
                title="[bold]INLINE VERIFICATION (source chunk text)[/bold]",
                border_style=pct_color, padding=(0, 2),
            ))
            v_results = verif.get("results", [])
            if v_results:
                t = _Tab(box=_box.SIMPLE, show_header=True, padding=(0, 1))
                t.add_column("Status",  style="bold",   width=5)
                t.add_column("Subject", style="cyan",   width=22)
                t.add_column("Relation",style="yellow", width=20)
                t.add_column("Object",  style="cyan",   width=22)
                t.add_column("Evidence / Reason", style="dim", width=50)
                for r in sorted(v_results, key=lambda x: x.get("verified", False)):
                    ok     = r.get("verified", False)
                    icon   = "[green]✓[/green]" if ok else "[red]✗[/red]"
                    subj   = (r.get("source_name") or r.get("subject_name") or "")[:22]
                    obj    = (r.get("target_name")  or r.get("object_name")  or "")[:22]
                    rel    = (r.get("relation") or r.get("label") or "")[:20]
                    detail = (r.get("supporting_text") or r.get("mismatch_reason") or "")[:50]
                    t.add_row(icon, subj, rel, obj, detail)
                _con.print(t)
            _con.print()
            import re as _re
            _html = _con.export_html(inline_styles=True)
            _body = _re.search(r'<pre[^>]*>(.*?)</pre>', _html, _re.DOTALL)
            if _body:
                emit({"layer": 8, "status": "log", "message": _body.group(1), "data": {"kind": "html"}})

        _rtext(emit, 8, "[bold magenta]  DEEP VERIFICATION  [/bold magenta]")
        _rtext(emit, 8,
               "  Verifies every triple against the source paper text — PMC/PubMed papers\n"
               "  are fetched online; PDFs use the text extracted during Layer 3.\n"
               "  Uses Greek-letter normalization, database alias lookup (NCBI Gene, MeSH,\n"
               "  Taxonomy), and abbreviated species names.\n"
               "  Generates [bold]verification_report.html[/bold] you can open in the browser.")

        ver_html   = None
        ver_json   = None
        deep_vdata = None
        try:
            from optional_modules import run_module
            _acc = run_module("accuracy",
                db_path    = staging_db,
                out_dir    = run_dir,
                fetch_text = True,
                formats    = output_format,
            )
            if _acc:
                deep_vdata = _acc
                if _acc.get("html_path") and Path(_acc["html_path"]).exists():
                    ver_html = Path(_acc["html_path"])
                    ver_json = Path(_acc["json_path"])
        except Exception as ev2:
            _log(emit, 8, f"  verification report skipped: {ev2}", "warn")
        _ckpt(doc_id, 8)

        if deep_vdata:
            from rich.console import Console as _Con2
            from rich.table import Table as _Tab2
            from rich.panel import Panel as _Panel2
            from rich import box as _box2
            dv_total    = deep_vdata.get("total", 0)
            dv_conf     = deep_vdata.get("confirmed", 0)
            dv_partial  = deep_vdata.get("partial", 0)
            dv_mismatch = deep_vdata.get("mismatch", 0)
            dv_unver    = deep_vdata.get("unverifiable", 0)
            dv_pct      = deep_vdata.get("pct", 0)
            pct_color   = "bright_green" if dv_pct >= 90 else ("yellow" if dv_pct >= 70 else "red")
            filled2     = round(dv_pct / 10)
            bar2        = f"[{pct_color}]{'█' * filled2}[/{pct_color}][dim]{'░' * (10 - filled2)}[/dim]"
            ver_pct     = dv_pct
            _con2 = _Con2(record=True, force_terminal=False, width=120)
            _con2.print(_Panel2(
                f"  {bar2}  [{pct_color}][bold]{dv_pct}%[/bold][/{pct_color}] "
                f"confirmed against full paper text\n\n"
                f"  [green]✓ CONFIRMED[/green]     {dv_conf:>4}   — both entities found, "
                f"supporting sentence located\n"
                f"  [yellow]~ PARTIAL[/yellow]       {dv_partial:>4}   — one entity found "
                f"(other may be abbreviated)\n"
                f"  [red]✗ MISMATCH[/red]      {dv_mismatch:>4}   — neither entity in paper "
                f"(possible extraction error)\n"
                f"  [dim]? UNVERIFIABLE[/dim]  {dv_unver:>4}   — paper text not accessible "
                f"(paywalled / no PMC)\n"
                f"  [bold]  TOTAL[/bold]         {dv_total:>4}",
                title=f"[bold magenta]DEEP VERIFICATION RESULTS[/bold magenta]",
                border_style=pct_color, padding=(0, 2),
            ))
            mismatches = [r for r in deep_vdata.get("results", []) if r.get("overall_status") == "MISMATCH"]
            if mismatches:
                _con2.print("[bold red]  MISMATCHES — review these extractions:[/bold red]")
                mt = _Tab2(box=_box2.SIMPLE, show_header=True, padding=(0, 1))
                mt.add_column("Subject",  style="cyan",   width=24)
                mt.add_column("Relation", style="yellow", width=20)
                mt.add_column("Object",   style="cyan",   width=24)
                mt.add_column("Note",     style="dim",    width=44)
                for r in mismatches:
                    note = r["sources"][0]["note"] if r.get("sources") else ""
                    mt.add_row(r.get("subject", "")[:24], r.get("relation", "")[:20],
                               r.get("object", "")[:24], note[:44])
                _con2.print(mt)
            if ver_html and ver_html.exists():
                _con2.print(f"  [green]✓[/green]  Report saved: [bold]{ver_html}[/bold]")
            _con2.print()
            import re as _re2
            _html2 = _con2.export_html(inline_styles=True)
            _body2 = _re2.search(r'<pre[^>]*>(.*?)</pre>', _html2, _re2.DOTALL)
            if _body2:
                emit({"layer": 8, "status": "log", "message": _body2.group(1), "data": {"kind": "html"}})

        graph_html = Path("")
        if run_dir.exists():
            import subprocess, sys as _sys
            _ROOT = Path(__file__).resolve().parents[2]
            try:
                res2 = subprocess.run(
                    [_sys.executable, "tools/visualize_graph.py",
                     "--run-dir", str(run_dir), "--output", str(run_dir / "graph.html")],
                    capture_output=True, text=True, cwd=str(_ROOT))
                if res2.returncode == 0:
                    graph_html = run_dir / "graph.html"
            except Exception:
                pass

        pln_graph_html = Path("")
        _pln_result    = {"stv_all": [], "derived": [], "contradictions": [], "revised": 0}
        if os.getenv("ENABLE_PLN", "false").lower() == "true":
            try:
                from optional_modules import run_module as _run_mod
                _pln_fmt = "neo4j" if output_format in ("neo4j", "both") else "metta"
                _pln = _run_mod("pln",
                    db_path = staging_db if staging_db.exists() else None,
                    out_dir = run_dir,
                    fmt     = _pln_fmt,
                )
                if _pln:
                    _pln_result    = _pln
                    pln_graph_html = Path(_pln["html_path"])
            except Exception as _pln_err:
                _log(emit, 8, f"  PLN module skipped: {_pln_err}")

        from rich.console import Console as _Con3
        from rich.panel import Panel as _Panel3
        _con3 = _Con3(record=True, force_terminal=False, width=120)
        fmt_label = {"neo4j": "Neo4j CSV", "metta": "MeTTa", "both": "Neo4j CSV + MeTTa"}.get(output_format, "")
        summary_lines = [
            "[bold bright_green]All 8 layers complete.[/bold bright_green]",
            f"[dim]Output format: {fmt_label}[/dim]",
            f"[dim]Run folder:    {run_dir}[/dim]",
            f"[dim]Human review:  data/kg_output/human_review.jsonl[/dim]",
        ]
        if v_total > 0:
            ic = "bright_green" if ver_pct >= 90 else ("yellow" if ver_pct >= 70 else "red")
            summary_lines.append(f"[{ic}]Inline check:  {v_ok}/{v_total} ({ver_pct}%) confirmed[/{ic}]")
        _con3.print(_Panel3.fit("\n".join(summary_lines), border_style="bright_green", padding=(1, 4)))
        _con3.print()
        import re as _re3
        _html3 = _con3.export_html(inline_styles=True)
        _body3 = _re3.search(r'<pre[^>]*>(.*?)</pre>', _html3, _re3.DOTALL)
        if _body3:
            emit({"layer": 8, "status": "log", "message": _body3.group(1), "data": {"kind": "html"}})

        _paper_metrics = {"precision": 0.0, "recall": 0.0, "f1": 0.0,
                          "tp": 0, "fp": 0, "fn": 0}
        try:
            from optional_modules.accuracy import run as _acc_run
            _acc = _acc_run(
                db_path    = staging_db,
                out_dir    = run_dir,
                fetch_text = True,
                formats    = output_format,
            )
            if _acc:
                _paper_metrics = {
                    "precision": _acc.get("precision", 0.0),
                    "recall":    _acc.get("recall",    0.0),
                    "f1":        _acc.get("f1",        0.0),
                    "tp":        _acc.get("tp",        0),
                    "fp":        _acc.get("fp",        0),
                    "fn":        _acc.get("fn",        0),
                }
                _log(emit, 8, (
                    f"  Precision: {_paper_metrics['precision']*100:.1f}%  "
                    f"Recall: {_paper_metrics['recall']*100:.1f}%  "
                    f"F1: {_paper_metrics['f1']*100:.1f}%  "
                    f"(TP={_paper_metrics['tp']} FP={_paper_metrics['fp']} FN={_paper_metrics['fn']})"
                ))
        except Exception as _acc_err:
            _log(emit, 8, f"  (accuracy metrics skipped: {_acc_err})", "warn")

        _emit(emit, 8, "done", f"{pub.get('auto_insert', 0)} triples written", {
            "auto_insert":    pub.get("auto_insert", 0),
            "human_review":   pub.get("human_review", 0),
            "neo4j_nodes":    neo4j.get("node_count", 0),
            "neo4j_edges":    neo4j.get("edge_count", 0),
            "metta_nodes":    metta.get("node_count", 0),
            "metta_edges":    metta.get("edge_count", 0),
            "verified":       verif.get("verified", 0),
            "total":          verif.get("total", 0),
            "ver_pct":        ver_pct,
            "run_dir":        str(run_dir),
            "graph_html":     str(graph_html)     if graph_html.exists()     else "",
            "pln_html":       str(pln_graph_html) if pln_graph_html.exists() else "",
            "pln_extracted":  _pln_result.get("stv_all", []) and len(_pln_result.get("stv_all", [])),
            "pln_inferred":   len(_pln_result.get("derived", [])),
            "ver_html":       str(ver_html) if ver_html and ver_html.exists() else "",
            "ver_results":    verif.get("results", [])[:35],
            "staging_db":     str(staging_db),
            "paper_precision": _paper_metrics["precision"],
            "paper_recall":    _paper_metrics["recall"],
            "paper_f1":        _paper_metrics["f1"],
            "paper_tp":        _paper_metrics["tp"],
            "paper_fp":        _paper_metrics["fp"],
            "paper_fn":        _paper_metrics["fn"],
        })
    except Exception as e:
        os.environ.pop("TRIPLE_STORE_PATH", None)
        _emit(emit, 8, "error", str(e))
