"use strict";

// ── Colour per entity type (stable hash → HSL) ───────────────────────────────
function typeColor(t) {
  let h = 0;
  for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) % 360;
  return `hsl(${h}, 55%, 45%)`;
}

const SAMPLES = [
  "BRCA1 and BRCA2 mutations confer a high lifetime risk of breast and ovarian cancer.",
  "The V600E missense mutation in BRAF constitutively activates MAPK signalling.",
  "Rapamycin inhibits mTORC1 by binding to the FKBP12-rapamycin complex.",
  "miR-21 is upregulated in most human cancers and targets the tumour suppressor PTEN.",
  "Dopaminergic neurons in the substantia nigra degenerate selectively in Parkinson disease.",
  "The MYC super-enhancer drives high-level transcription of MYC in multiple myeloma.",
  "CTCF-mediated chromatin loops bring distal enhancers into proximity with gene promoters.",
  "In aged C57BL/6J mice fed a high-fat diet, rapamycin restored mTORC1-dependent autophagy and reduced senescent cell burden in adipose tissue.",
];

// ── Helpers ──────────────────────────────────────────────────────────────────
function $(sel) { return document.querySelector(sel); }
function $all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
function selectedModels() {
  return $all(".model-cb:checked").map((cb) => cb.value);
}
function esc(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function modelName(key) {
  const row = $(`.model-row[data-key="${key}"] .model-name`);
  return row ? row.textContent.trim() : key;
}

// ── Model selection buttons ──────────────────────────────────────────────────
$("#select-all").onclick = () => $all(".model-cb").forEach((cb) => (cb.checked = true));
$("#select-none").onclick = () => $all(".model-cb").forEach((cb) => (cb.checked = false));
$("#select-cpu").onclick = () =>
  $all(".model-row").forEach((row) => {
    row.querySelector(".model-cb").checked = row.dataset.gpu === "0";
  });

// ── Tabs ─────────────────────────────────────────────────────────────────────
$all(".tab").forEach((tab) => {
  tab.onclick = () => {
    $all(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    $all(".tab-body").forEach((b) => b.classList.add("hidden"));
    $(`#tab-${tab.dataset.tab}`).classList.remove("hidden");
  };
});

// ── Sample sentences ─────────────────────────────────────────────────────────
const sel = $("#sample-select");
SAMPLES.forEach((s, i) => {
  const o = document.createElement("option");
  o.value = String(i);
  o.textContent = s.length > 70 ? s.slice(0, 70) + "…" : s;
  sel.appendChild(o);
});
sel.onchange = () => {
  if (sel.value !== "") $("#input-text").value = SAMPLES[+sel.value];
};

// ── Entity highlighting ──────────────────────────────────────────────────────
function renderHighlighted(text, entities) {
  // Sort by start; on overlap, keep the longer span (skip nested).
  const sorted = entities.slice().sort((a, b) => a.start - b.start || b.end - a.end);
  let html = "";
  let cursor = 0;
  for (const e of sorted) {
    if (e.start < cursor) continue; // overlapping — skip
    html += esc(text.slice(cursor, e.start));
    const c = typeColor(e.label);
    html += `<span class="ent" style="background:${c}33;border-bottom-color:${c}" title="${esc(e.label)} (${e.score})">` +
            esc(text.slice(e.start, e.end)) +
            `<span class="ent-label" style="color:${c}">${esc(e.label)}</span></span>`;
    cursor = e.end;
  }
  html += esc(text.slice(cursor));
  return html;
}

function renderExtractCard(text, r) {
  if (r.error) {
    return `<div class="result-card"><div class="result-head"><span class="result-title">${esc(modelName(r.key))}</span></div>` +
           `<div class="err">${esc(r.error)}</div></div>`;
  }
  const n = r.entities.length;
  const cold = r.cold_start ? ' · <b>cold start</b> (incl. load)' : "";
  const chips = r.entities
    .map((e) => {
      const c = typeColor(e.label);
      return `<span class="chip" style="border-color:${c}88">${esc(e.text)}<span class="chip-type" style="color:${c}">${esc(e.label)}</span></span>`;
    })
    .join("");
  return `<div class="result-card">
    <div class="result-head">
      <span class="result-title">${esc(modelName(r.key))}</span>
      <span class="result-stat"><b>${n}</b> entities · <b>${r.latency_ms}</b> ms${cold}</span>
    </div>
    <div class="highlighted">${renderHighlighted(text, r.entities)}</div>
    <div class="ent-list">${chips || '<span class="result-stat">no entities found</span>'}</div>
  </div>`;
}

$("#run-extract").onclick = async () => {
  const text = $("#input-text").value.trim();
  const models = selectedModels();
  if (!text) return alert("Enter some text.");
  if (!models.length) return alert("Select at least one model.");

  const btn = $("#run-extract");
  btn.disabled = true;
  $("#extract-status").textContent = "Running… (first use of a model downloads/loads it)";
  $("#extract-results").innerHTML = "";
  try {
    const resp = await fetch("/api/predict", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, models }),
    });
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    $("#extract-results").innerHTML = data.results.map((r) => renderExtractCard(data.text, r)).join("");
    $("#extract-status").textContent = `Done — ${data.results.length} model(s).`;
  } catch (e) {
    $("#extract-status").innerHTML = `<span class="err">${esc(String(e))}</span>`;
  } finally {
    btn.disabled = false;
  }
};

// ── Benchmark ────────────────────────────────────────────────────────────────
const BENCH_COLS = [
  { k: "partial_f1", label: "Partial F1", path: (r) => r.overall.partial_f1, bar: true },
  { k: "tier1_f1", label: "Tier-1 F1", path: (r) => r.tier1_only.partial_f1, bar: true },
  { k: "exact_f1", label: "Exact F1", path: (r) => r.overall.exact_f1 },
  { k: "precision", label: "Precision", path: (r) => r.overall.partial_precision },
  { k: "recall", label: "Recall", path: (r) => r.overall.partial_recall },
  { k: "coverage", label: "Coverage %", path: (r) => r.type_coverage_pct },
  { k: "avg_ms", label: "Avg ms", path: (r) => r.avg_latency_ms },
  { k: "p95_ms", label: "P95 ms", path: (r) => r.p95_latency_ms },
  { k: "gpu_mb", label: "GPU MB", path: (r) => r.gpu_peak_mb },
];

let _benchData = [];
let _sortKey = "partial_f1";

function renderBenchTable() {
  const ok = _benchData.filter((r) => r.ok);
  const bad = _benchData.filter((r) => !r.ok);
  const col = BENCH_COLS.find((c) => c.k === _sortKey) || BENCH_COLS[0];
  ok.sort((a, b) => col.path(b) - col.path(a));

  const maxF1 = Math.max(0.01, ...ok.map((r) => r.overall.partial_f1));
  let html = "<table class='bench'><thead><tr><th>Model</th>";
  BENCH_COLS.forEach((c) => {
    html += `<th data-sort="${c.k}">${c.label}${_sortKey === c.k ? " ▾" : ""}</th>`;
  });
  html += "</tr></thead><tbody>";
  ok.forEach((r, i) => {
    html += `<tr><td><span class="rank">${i + 1}.</span> ${esc(r.model)}</td>`;
    BENCH_COLS.forEach((c) => {
      const v = c.path(r);
      if (c.bar && c.k === "partial_f1") {
        const w = (r.overall.partial_f1 / maxF1) * 100;
        html += `<td class="bar-cell"><span class="bar" style="width:${w}%"></span><span class="bar-val">${v}</span></td>`;
      } else {
        html += `<td>${v}</td>`;
      }
    });
    html += "</tr>";
  });
  bad.forEach((r) => {
    html += `<tr class="bad-row"><td>${esc(r.model)}</td><td colspan="${BENCH_COLS.length}">${esc(r.error || "failed")}</td></tr>`;
  });
  html += "</tbody></table>";

  // Charts
  html += "<div class='charts'>";
  html += hbarChart("Partial F1", ok, (r) => r.overall.partial_f1, 1, "#3B9ED8");
  const maxMs = Math.max(1, ...ok.map((r) => r.avg_latency_ms));
  html += hbarChart("Avg latency (ms)", ok, (r) => r.avg_latency_ms, maxMs, "#EF9F27");
  html += "</div>";

  $("#benchmark-results").innerHTML = html;
  $all("table.bench th[data-sort]").forEach((th) => {
    th.onclick = () => { _sortKey = th.dataset.sort; renderBenchTable(); };
  });
}

function hbarChart(title, rows, valFn, max, color) {
  const sorted = rows.slice().sort((a, b) => valFn(b) - valFn(a));
  let h = `<div class="chart"><h3>${title}</h3>`;
  sorted.forEach((r) => {
    const v = valFn(r);
    const w = Math.max(1, (v / max) * 100);
    h += `<div class="hbar-row"><span class="hbar-label" title="${esc(r.model)}">${esc(r.model)}</span>` +
         `<span class="hbar-track"><span class="hbar-fill" style="width:${w}%;background:${color}"></span></span>` +
         `<span class="hbar-num">${v}</span></div>`;
  });
  h += "</div>";
  return h;
}

$("#run-benchmark").onclick = async () => {
  const models = selectedModels();
  if (!models.length) return alert("Select at least one model.");
  const btn = $("#run-benchmark");
  btn.disabled = true;
  $("#benchmark-status").textContent = "Benchmarking… this can take a while for heavy models.";
  try {
    const resp = await fetch("/api/benchmark", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ models, force: $("#force-bench").checked }),
    });
    const data = await resp.json();
    _benchData = data.results;
    _sortKey = "partial_f1";
    renderBenchTable();
    $("#benchmark-status").textContent = `Done — ${data.results.length} model(s) scored.`;
  } catch (e) {
    $("#benchmark-status").innerHTML = `<span class="err">${esc(String(e))}</span>`;
  } finally {
    btn.disabled = false;
  }
};
