"""
Lightweight timing / debug instrumentation for the pipeline.

Every layer and heavy core component reports how long it took, what it
produced, and (optionally) a per-run summary table. Output goes to stderr so
it never pollutes the structured stdout the web UI consumes — and, when an
``emit`` callback is supplied, a compact ``⏱`` line is also streamed to the UI.

Toggle everything with the ``PIPELINE_TIMING`` env var (default: on):

    PIPELINE_TIMING=0   # silence all timing output

Usage
-----
    from src.timing import timed, log_timing, StageTimer

    # 1. Context manager — time a block, auto-log on exit:
    with timed("Layer 4 — NER ensemble", emit=emit, layer=4) as t:
        tagged = preextractor.process_batch(chunks)
        t.detail(f"{len(tagged)} chunks tagged")

    # 2. Manual span:
    log_timing("Step 3 — Cleaning", 0.42, detail="12,345 → 9,876 chars")

    # 3. Whole-run rollup:
    st = StageTimer()
    st.record("Layer 1", 0.01); st.record("Layer 2", 0.03); ...
    st.summary(emit=emit)
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager


def timing_enabled() -> bool:
    """Timing output is on unless PIPELINE_TIMING is explicitly falsy."""
    return os.getenv("PIPELINE_TIMING", "1").strip().lower() not in ("0", "false", "no", "off", "")


def _fmt_secs(seconds: float) -> str:
    """Human-friendly duration: 850ms · 3.2s · 1m04s."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    m, s = divmod(seconds, 60)
    return f"{int(m)}m{s:04.1f}s"


def log_timing(label: str, seconds: float, *, detail: str = "",
               emit=None, layer: int = 0, indent: int = 0) -> None:
    """Emit one ``⏱`` timing line to stderr (always) and the UI (if emit given).

    ``label``   — what was measured (e.g. "Layer 4 — NER ensemble").
    ``seconds`` — elapsed wall-clock time.
    ``detail``  — optional output description ("42 chunks tagged").
    ``indent``  — nesting depth for sub-steps (2 spaces each).
    """
    if not timing_enabled():
        return
    pad = "  " * indent
    tail = f"  →  {detail}" if detail else ""
    line = f"⏱ {pad}{label}: {_fmt_secs(seconds)}{tail}"
    sys.stderr.write(line + "\n")
    sys.stderr.flush()
    if emit is not None:
        try:
            emit({"layer": layer, "status": "log", "message": line,
                  "data": {"kind": "timing", "seconds": round(seconds, 4),
                           "label": label, "detail": detail}})
        except Exception:
            pass


@contextmanager
def timed(label: str, *, emit=None, layer: int = 0, indent: int = 0,
          stage_timer: "StageTimer | None" = None):
    """Time the wrapped block; log a ``⏱`` line on exit (even on exception).

    Yields a small handle whose ``.detail(str)`` sets the output description
    shown in the timing line, and whose ``.elapsed`` is readable mid-block.
    """
    class _Handle:
        def __init__(self):
            self._detail = ""
            self._start = time.perf_counter()

        @property
        def elapsed(self) -> float:
            return time.perf_counter() - self._start

        def detail(self, text: str) -> None:
            self._detail = text

    handle = _Handle()
    start = time.perf_counter()
    try:
        yield handle
    finally:
        elapsed = time.perf_counter() - start
        log_timing(label, elapsed, detail=handle._detail,
                   emit=emit, layer=layer, indent=indent)
        if stage_timer is not None:
            stage_timer.record(label, elapsed, detail=handle._detail)


class StageTimer:
    """Accumulate per-stage durations and print a final rollup table."""

    def __init__(self):
        self._rows: list[tuple[str, float, str]] = []
        self._t0 = time.perf_counter()

    def record(self, label: str, seconds: float, detail: str = "") -> None:
        self._rows.append((label, seconds, detail))

    @contextmanager
    def stage(self, label: str, *, emit=None, layer: int = 0):
        """Time a stage and auto-record it into this rollup."""
        with timed(label, emit=emit, layer=layer, stage_timer=self) as h:
            yield h

    def total(self) -> float:
        return time.perf_counter() - self._t0

    def summary(self, *, emit=None, title: str = "PIPELINE TIMING SUMMARY") -> None:
        """Print an aligned per-stage table with % of total and a grand total."""
        if not timing_enabled() or not self._rows:
            return
        total = sum(s for _, s, _ in self._rows) or 1e-9
        width = max((len(lbl) for lbl, _, _ in self._rows), default=10)

        lines = [
            "",
            f"┌─ {title} " + "─" * max(2, 46 - len(title)),
        ]
        for label, seconds, detail in self._rows:
            pct = seconds / total * 100
            bar = "█" * int(round(pct / 5))  # 20-cell bar, one cell per 5%
            row = f"│ {label:<{width}}  {_fmt_secs(seconds):>8}  {pct:4.0f}%  {bar}"
            if detail:
                row += f"  {detail}"
            lines.append(row)
        lines.append("│ " + "─" * (width + 26))
        lines.append(f"│ {'TOTAL':<{width}}  {_fmt_secs(total):>8}")
        lines.append("└" + "─" * 48)

        text = "\n".join(lines)
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
        if emit is not None:
            try:
                emit({"layer": 0, "status": "log", "message": text,
                      "data": {"kind": "timing_summary",
                               "stages": [{"label": l, "seconds": round(s, 4),
                                           "detail": d} for l, s, d in self._rows],
                               "total": round(total, 4)}})
            except Exception:
                pass
