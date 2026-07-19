/* Bio Semantic Parser — Web UI */

let fmt            = 'both';
let pdfFile        = null;
let isPdf          = false;
let selectedSource = '';   // source name locked by header chip click

// ── Atomspace commit ─────────────────────────────────────────────────────────

let _stagingDb    = '';
let _commitFormat = 'both';
let _docId        = '';

function setCommitFmt(f, btn) {
  document.querySelectorAll('#commit-fmt-group .fmt-chip').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _commitFormat = f;
  // Refresh breakdown when format changes — n_already depends on which DB is checked
  if (_stagingDb) fetchStagingBreakdown(_stagingDb, _commitFormat);
}

async function commitToAtomspace() {
  if (!_stagingDb) { alert('No staging data to commit.'); return; }
  const btn = document.getElementById('commit-btn');
  btn.disabled = true; btn.textContent = '⟳ Committing…';

  const fd = new FormData();
  fd.append('staging_db',    _stagingDb);
  fd.append('output_format', _commitFormat);
  fd.append('doc_id',        _docId);
  const resp = await fetch('/api/commit', { method:'POST', body:fd });
  const d    = await resp.json();

  const res = document.getElementById('commit-result');
  res.style.display = 'block';
  if (d.ok) {
    const newN = d.new || 0;
    const updN = d.updated || 0;
    res.innerHTML = `<div style="color:var(--green);font-size:13px;font-weight:600;margin-bottom:10px">
      ✓ ${newN} new triple(s) committed${updN > 0 ? ` · ${updN} updated` : ''} — unified ${d.format} atomspace
    </div>`;
    btn.textContent = '✓ Committed';

    // Rebuild compare pages then show just the Compare buttons
    if (_stagingDb) rebuildComparePages(d);
    // Show PLN commit step after successful KG commit — only if PLN is enabled
    if (_PLN_ENABLED) document.getElementById('pln-commit-step').style.display = 'block';
    // Persist commit result — buttons are added by rebuildComparePages after async call
    AppState.saveCommit(_commitFormat, d, '');
  } else {
    res.innerHTML = `<div style="color:var(--red);font-size:12px">Error: ${d.error||'Unknown error'}</div>`;
    btn.disabled = false; btn.textContent = '✓ Commit to Unified KG';
  }
}

// PLN commit — triggers Layer 9 PLN reasoning and writes to unified_metta/pln/
async function commitPLN() {
  const btn = document.getElementById('pln-commit-btn');
  btn.disabled = true; btn.textContent = '🔮 Running PLN…';
  const res = document.getElementById('pln-commit-result');
  res.style.display = 'block';
  res.innerHTML = '<span style="color:var(--text3)">Running PLN reasoning (revision · inference · contradictions)…</span>';
  try {
    const resp = await fetch('/api/run_pln', { method:'POST' });
    const d    = await resp.json();
    if (d.ok) {
      res.innerHTML = `<div style="color:var(--pln);font-size:13px;font-weight:600">
        🔮 PLN committed — ${d.revised||0} revised · ${d.inferred||0} inferred · ${d.contradictions||0} contradictions
      </div>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        ${d.pln_html ? `<button class="fmt-chip" style="border-color:var(--pln2);color:var(--pln)" onclick="openViewer('${fileUrl(d.pln_html)}','Unified PLN AtomSpace')">🔮 Unified PLN ↗</button>` : ''}
      </div>`;
      btn.textContent = '🔮 PLN Committed';
      AppState.savePLN(d);              // persist PLN result
    } else {
      res.innerHTML = `<div style="color:var(--red);font-size:12px">PLN error: ${d.error||d.trace||'Server returned ok=false — restart the frontend server'}</div>`;
      btn.disabled = false; btn.textContent = '🔮 Commit to Unified PLN';
    }
  } catch(e) {
    res.innerHTML = `<div style="color:var(--red);font-size:12px">
      Network error — likely the /api/run_pln endpoint is not registered.<br>
      Restart the server: <code>python3 -m uvicorn frontend.app:app --reload</code><br>
      Error: ${e.message}
    </div>`;
    btn.disabled = false; btn.textContent = '🔮 Commit to Unified PLN';
  }
}

async function rebuildComparePages(commitData) {
  if (!_outputData || !_outputData.run_dir) return;
  try {
    const fd = new FormData();
    fd.append('run_dir', _outputData.run_dir);
    const r = await fetch('/api/rebuild-compare', { method:'POST', body:fd });
    const d = await r.json();
    const res = document.getElementById('commit-result');
    if (!res) return;
    // Show only Compare buttons — they contain everything inside tabs
    let btns = '<div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">';
    btns += '<span style="font-size:11px;color:var(--text3);font-weight:600;text-transform:uppercase;letter-spacing:.05em">Open in browser →</span>';
    if (d.ok && d.neo4j_compare)
      btns += `<button class="fmt-chip" style="border-color:var(--blue)" onclick="openViewer('${fileUrl(d.neo4j_compare)}','Neo4j Compare')">⇄ Neo4j Compare ↗</button>`;
    if (d.ok && d.metta_compare)
      btns += `<button class="fmt-chip" style="border-color:var(--purple)" onclick="openViewer('${fileUrl(d.metta_compare)}','MeTTa Compare')">⇄ MeTTa Compare ↗</button>`;
    // PLN button — only shown when PLN sidecar is enabled
    if (_PLN_ENABLED) {
      const plnPath = '/api/file?path=' + encodeURIComponent('data/kg_output/unified_metta/pln_graph.html');
      btns += `<button class="fmt-chip" style="border-color:var(--pln2);color:var(--pln)" onclick="openViewer('${plnPath}','Unified PLN AtomSpace')">🔮 PLN ↗</button>`;
    }
    btns += '</div>';
    res.innerHTML += btns;
  } catch(e) {}
}

function showRunDirButtons(runDir) {
  const res = document.getElementById('commit-result');
  if (!res || !runDir) return;
  // Only show Compare buttons — Paper Graph and Verification Report removed
  const files = [
    ['⇄ Neo4j Compare',  runDir + '/compare_neo4j.html'],
    ['⇄ MeTTa Compare',  runDir + '/compare_metta.html'],
  ];
  let links = '<div style="margin-top:10px"><div style="font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">Run outputs</div><div style="display:flex;gap:6px;flex-wrap:wrap">';
  for (const [label, path] of files) {
    const apiUrl = `/api/file?path=${encodeURIComponent(path)}`;
    links += `<button class="fmt-chip" onclick="openOrCheck('${apiUrl}','${label}')">${label} ↗</button>`;
  }
  links += '</div></div>';
  res.innerHTML += links;
}

function openOrCheck(src, title) {
  if (!src || src === 'undefined' || src === '') {
    alert(`${title} not generated yet — run the pipeline first.`);
    return;
  }
  openViewer(src, title);
}

// ── Run selector — shown when multiple runs of the same paper exist ──────────
// ── Existing output actions — shown when loading a previously-processed paper ─
function _showExistingOutputActions(d) {
  const old = document.getElementById('existing-actions');
  if (old) old.remove();

  const docId = d.doc_id || '';
  const wrap  = document.createElement('div');
  wrap.id = 'existing-actions';
  wrap.style.cssText = `
    background:var(--bg2);border:1px solid var(--border);border-radius:12px;
    padding:20px 24px;margin-top:16px;margin-bottom:24px;
  `;
  const completedLayers = d.completed_layers || [];
  const nextLayer       = d.next_layer || null;
  const allDone         = completedLayers.length >= 8;

  // Build layer selector — user can resume from any layer 1–8
  const layerNames = ['','Source','Dedup','Fetch','NER','Schema','Extract','Validate','Publish'];
  const layerSelector = `
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px;
      padding:10px 12px;background:var(--bg3);border-radius:8px;border:1px solid var(--border)">
      <span style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;
        letter-spacing:.05em;white-space:nowrap">Resume from:</span>
      ${[3,4,5,6,7,8].map(n => {
        const done  = completedLayers.includes(n);
        const isNext = n === nextLayer;
        const color  = isNext ? 'var(--blue)' : done ? 'var(--green)' : 'var(--border)';
        const bg     = isNext ? 'var(--bg)' : done ? 'var(--bg2)' : 'var(--bg3)';
        const label  = `L${n} ${layerNames[n]}`;
        return `<button class="fmt-chip"
          style="border-color:${color};color:${isNext?'var(--blue)':done?'var(--green)':'var(--text3)'};
            background:${bg};font-size:10px;padding:3px 9px"
          data-action="resume-layer" data-docid="${esc(docId)}" data-layer="${n}"
          title="Re-run from Layer ${n}: ${layerNames[n]}${done?' (completed)':isNext?' (next)':' (not run)'}">
          ${label}
        </button>`;
      }).join('')}
    </div>`;

  const statusLine = !allDone && nextLayer
    ? `Layers ${completedLayers.join(', ')} completed. Pipeline stopped at Layer ${nextLayer}.`
    : `All layers complete. Open existing outputs above, or re-run from any layer below:`;

  wrap.innerHTML = `
    <div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:6px">
      Existing outputs loaded
    </div>
    <div style="font-size:12px;color:var(--text3);margin-bottom:12px">
      ${statusLine}
    </div>
    ${layerSelector}
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <button class="fmt-chip" style="background:var(--bg3);border:1px solid var(--green2);color:var(--text)"
        data-action="commit-kg" data-rundir="${esc(d.run_dir||'')}" data-docid="${esc(docId)}"
        title="Commit existing triples to the unified atomspace">
        Commit to Unified KG
      </button>
      ${_PLN_ENABLED ? `<button class="fmt-chip" style="border-color:var(--pln2);color:var(--pln)"
        data-action="commit-pln"
        title="Run PLN reasoning and commit to unified MeTTa PLN">
        🔮 Commit to Unified PLN
      </button>` : ''}
      <button class="fmt-chip" style="border-color:var(--border);color:var(--text2)"
        data-action="reprocess" data-docid="${esc(docId)}"
        title="Discard existing outputs and reprocess from scratch">
        Reprocess from scratch
      </button>
    </div>
    <div id="existing-action-result" style="margin-top:12px;display:none"></div>
  `;

  const output = document.getElementById('output');
  if (output && output.parentNode) output.parentNode.insertBefore(wrap, output.nextSibling);

  // Attach listeners via JS — no inline onclick, avoids scope issues
  wrap.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', function() {
      const action  = this.dataset.action;
      const runDir  = this.dataset.rundir || '';
      const dId     = this.dataset.docid  || '';
      if (action === 'commit-kg')    _commitExistingOutputs(runDir, dId);
      if (action === 'commit-pln')   _commitExistingPLN();
      if (action === 'reprocess')    _reprocessPaper(dId);
      if (action === 'resume')       _resumePipeline(dId, parseInt(this.dataset.layer||'1'));
      if (action === 'resume-layer') _resumeFromLayer(dId, parseInt(this.dataset.layer||'1'));
    });
  });
}

async function _commitExistingOutputs(runDir, docId) {
  const res = document.getElementById('existing-action-result');
  res.style.display = 'block';
  res.innerHTML = '<span style="color:var(--text3)">Committing…</span>';
  try {
    const fd = new FormData();
    fd.append('run_dir', runDir);
    fd.append('doc_id',  docId);
    fd.append('output_format', _commitFormat || 'both');
    const r = await fetch('/api/commit_existing', { method:'POST', body:fd });
    const d = await r.json();
    if (d.ok) {
      const msg   = d.message || `${d.new||0} new triple(s) committed`;
      const color = (d.new||0) === 0 ? 'var(--text3)' : 'var(--green)';
      // Build view buttons — same as post-commit in normal flow
      let viewBtns = '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">';
      viewBtns += '<span style="font-size:11px;color:var(--text3);font-weight:600;text-transform:uppercase;letter-spacing:.05em">Open →</span>';
      if (d.neo4j_compare) viewBtns += `<button class="fmt-chip" style="border-color:var(--blue)" data-open="${d.neo4j_compare}">⇄ Neo4j Compare ↗</button>`;
      if (d.metta_compare) viewBtns += `<button class="fmt-chip" style="border-color:var(--purple)" data-open="${d.metta_compare}">⇄ MeTTa Compare ↗</button>`;
      viewBtns += '</div>';
      res.innerHTML = `<div style="color:${color};font-size:13px;font-weight:600;margin-bottom:4px">
        ✓ ${msg} — unified ${d.format||''} atomspace
      </div>${viewBtns}`;
      // Wire open buttons via event listener
      res.querySelectorAll('[data-open]').forEach(btn => {
        btn.addEventListener('click', () => {
          openViewer('/api/file?path=' + encodeURIComponent(btn.dataset.open), btn.textContent.trim().replace(' ↗',''));
        });
      });
      // Show PLN commit step only if PLN is enabled
      if (_PLN_ENABLED) document.getElementById('pln-commit-step').style.display = 'block';
    } else {
      res.innerHTML = `<div style="color:var(--red);font-size:12px">Error: ${d.error||'unknown'}</div>`;
    }
  } catch(e) {
    res.innerHTML = `<div style="color:var(--red);font-size:12px">Network error: ${e.message}</div>`;
  }
}

async function _commitExistingPLN() {
  const res = document.getElementById('existing-action-result');
  if (res) { res.style.display = 'block'; res.innerHTML = '<span style="color:var(--text3)">🔮 Running PLN reasoning…</span>'; }
  try {
    const resp = await fetch('/api/run_pln', { method: 'POST' });
    const d    = await resp.json();
    if (d.ok) {
      if (res) res.innerHTML = `<div style="color:var(--pln);font-size:13px;font-weight:600">
        🔮 PLN committed — ${d.revised||0} revised · ${d.inferred||0} inferred · ${d.contradictions||0} contradictions
        ${d.pln_html ? `<span style="margin-left:10px"><button class="fmt-chip" style="border-color:var(--pln2);color:var(--pln)"
          data-open="${d.pln_html}">🔮 Open PLN graph ↗</button></span>` : ''}
      </div>`;
      // Wire the open button
      res && res.querySelectorAll('[data-open]').forEach(btn => {
        btn.addEventListener('click', () => openViewer('/api/file?path=' + encodeURIComponent(btn.dataset.open), 'Unified PLN AtomSpace'));
      });
    } else {
      if (res) res.innerHTML = `<div style="color:var(--red);font-size:12px">PLN error: ${d.error||d.trace||'Unknown'}</div>`;
    }
  } catch(e) {
    if (res) res.innerHTML = `<div style="color:var(--red);font-size:12px">Network error: ${e.message}</div>`;
  }
}

function _showPreRunLayerSelector(docId, completedLayers, nextLayer, displayName) {
  displayName = displayName || docId;
  // Remove any existing pre-run prompt
  document.getElementById('pre-run-prompt')?.remove();

  const layerNames = ['','Source','Dedup','Fetch','NER','Schema','Extract','Validate','Publish'];
  const wrap = document.createElement('div');
  wrap.id = 'pre-run-prompt';
  wrap.style.cssText = `
    background:var(--bg2);border:1px solid var(--blue);border-radius:12px;
    padding:20px 24px;margin-top:16px;margin-bottom:16px;
  `;

  const layerBtns = [3,4,5,6,7,8].map(n => {
    const done   = completedLayers.includes(n);
    const isNext = n === nextLayer;
    const clr    = isNext ? 'var(--blue)' : done ? 'var(--green)' : 'var(--border)';
    const txtClr = isNext ? 'var(--blue)' : done ? 'var(--green)' : 'var(--text3)';
    return `<button class="fmt-chip"
      style="border-color:${clr};color:${txtClr};font-size:10px;padding:3px 9px"
      onclick="_startFromLayer(${JSON.stringify(docId).replace(/"/g,'&quot;')},${n})"
      title="${done?'Completed':'Not run yet'} — click to start from Layer ${n}">
      L${n} ${layerNames[n]}
    </button>`;
  }).join('');

  wrap.innerHTML = `
    <div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:6px">
      Checkpoint found for <span style="color:var(--blue)">${esc(displayName)}</span>
    </div>
    <div style="font-size:12px;color:var(--text3);margin-bottom:12px">
      ${nextLayer
        ? `Layers ${completedLayers.join(', ')} completed — pipeline stopped at Layer ${nextLayer} (${layerNames[nextLayer]}).`
        : `All layers completed previously.`}
      Choose which layer to re-run from, or run fresh.
    </div>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px;
      padding:10px 12px;background:var(--bg3);border-radius:8px">
      <span style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.05em">
        Start from:
      </span>
      ${layerBtns}
    </div>
    <div style="display:flex;gap:10px">
      ${nextLayer ? `<button class="fmt-chip" style="border-color:var(--green);color:var(--green)"
        onclick="_startFromLayer('${esc(docId)}',${nextLayer})">
        Continue from Layer ${nextLayer}
      </button>` : ''}
      <button class="fmt-chip" style="border-color:var(--border);color:var(--text2)"
        onclick="_dismissPreRun()">
        Run completely fresh
      </button>
    </div>
  `;

  const hero = document.querySelector('.hero');
  if (hero) hero.after(wrap);
  else document.getElementById('output')?.before(wrap);
}

async function _startFromLayer(docId, fromLayer) {
  document.getElementById('pre-run-prompt')?.remove();
  await _resumeFromLayer(docId, fromLayer);
}

let _skipCheckpointCheck = false;  // set true to bypass pre-run check once

function _dismissPreRun() {
  document.getElementById('pre-run-prompt')?.remove();
  // Discard checkpoint and run fresh
  const val = document.getElementById('smart-input').value.trim();
  const fd  = new FormData();
  fd.append('doc_id', val);
  fetch('/api/discard-paper', {method:'POST', body:fd})
    .catch(()=>{})
    .finally(() => {
      _skipCheckpointCheck = true;
      startRun();           // re-call startRun — checkpoint is gone so it runs normally
    });
}

function _resumePipeline(docId, fromLayer) {
  // Kept for backward compatibility — calls the full resume-layer flow
  _resumeFromLayer(docId, fromLayer);
}

async function _resumeFromLayer(docId, fromLayer) {
  const layerNames = ['','Source','Dedup','Fetch','NER','Schema','Extract','Validate','Publish'];
  const name = layerNames[fromLayer] || `Layer ${fromLayer}`;

  // Show what we're about to do
  const res = document.getElementById('existing-action-result');
  if (res) { res.style.display = 'block'; res.innerHTML = `<span style="color:var(--text3)">Preparing to resume from Layer ${fromLayer} (${name})…</span>`; }

  if (!docId) {
    if (res) res.innerHTML = `<span style="color:var(--red)">Error: no paper ID found. Please re-enter the paper ID above and try again.</span>`;
    return;
  }

  if (!confirm(`Resume "${docId}" from Layer ${fromLayer} — ${name}?\n\nLayers ${fromLayer}–8 will re-run.\nLayers 1–${fromLayer > 3 ? fromLayer-1 : 2} will be skipped.`)) {
    if (res) res.style.display = 'none';
    return;
  }

  if (res) res.innerHTML = `<span style="color:var(--text3)">Resetting checkpoint for ${docId}…</span>`;

  // 1. Reset checkpoint
  const fd = new FormData();
  fd.append('doc_id',     docId);
  fd.append('from_layer', String(fromLayer));
  try {
    const r = await fetch('/api/resume-from-layer', { method:'POST', body:fd });
    const d = await r.json();
    if (!d.ok) {
      if (res) res.innerHTML = `<span style="color:var(--red)">Checkpoint reset failed: ${d.error}</span>`;
      return;
    }
    if (res) res.innerHTML = `<span style="color:var(--green)">Checkpoint reset — kept layers ${JSON.stringify(d.kept_layers)}. Starting pipeline…</span>`;
  } catch(e) {
    if (res) res.innerHTML = `<span style="color:var(--red)">Server error: ${e.message}</span>`;
    return;
  }

  // 2. Start pipeline — skip checkpoint check so we don't loop back to selector
  _skipCheckpointCheck = true;
  document.getElementById('pre-run-prompt')?.remove();
  AppState.clear();
  document.getElementById('existing-actions')?.remove();
  const inp = document.getElementById('smart-input');
  if (inp) { inp.value = docId; detectInput(docId); }
  startRun();
}

async function _reprocessPaper(docId) {
  if (!confirm(`Reprocess "${docId}" from scratch?\n\nThis will delete all existing outputs and run all 8 layers again.`)) return;

  // 1. Tell server to delete all existing outputs for this paper
  const fd = new FormData();
  fd.append('doc_id', docId);
  try {
    const r = await fetch('/api/discard-paper', { method:'POST', body:fd });
    const d = await r.json();
    if (!d.ok) {
      alert(`Could not clear existing data: ${d.error}`);
      return;
    }
  } catch(e) {
    alert(`Server error while clearing data: ${e.message}`);
    return;
  }

  // 2. Reset UI and start fresh pipeline run
  AppState.clear();
  const inp = document.getElementById('smart-input');
  if (inp) { inp.value = docId; detectInput(docId); }
  // Remove existing-actions card so it doesn't linger
  document.getElementById('existing-actions')?.remove();
  startRun();
}

// ── Run selector — shown when multiple runs of the same paper exist ──────────
function _showRunSelector(runs, baseData) {
  // Remove any existing selector
  const old = document.getElementById('run-selector');
  if (old) old.remove();

  const wrap = document.createElement('div');
  wrap.id = 'run-selector';
  wrap.style.cssText = `
    background:var(--bg2);border:1px solid var(--border);border-radius:12px;
    padding:16px 20px;margin-bottom:16px;
  `;

  const cards = runs.map((r, i) => {
    const name  = r.run_name || r.run_dir.split('/').pop();
    const date  = name.match(/\d{4}-\d{2}-\d{2}_\d{2}-\d{2}/)?.[0]?.replace('_',' ') || name;
    const isFirst = i === 0;
    return `<div style="
        background:${isFirst?'var(--bg3)':'var(--bg)'};
        border:1px solid ${isFirst?'var(--blue)':'var(--border)'};
        border-radius:8px;padding:10px 14px;cursor:pointer;transition:border-color .15s;
        ${isFirst?'':'opacity:.8'}
      "
      onclick="_switchRun(${JSON.stringify(r).replace(/"/g,'&quot;')}, this)"
      title="Open this run">
      <div style="font-size:12px;font-weight:600;color:var(--text)">${date}</div>
      <div style="font-size:10px;color:var(--text3);margin-top:2px">${r.run_dir.split('/').pop()}</div>
      ${isFirst?'<div style="font-size:10px;color:var(--blue);margin-top:2px">Latest ✓</div>':''}
    </div>`;
  }).join('');

  wrap.innerHTML = `
    <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;
                letter-spacing:.06em;margin-bottom:10px">
      ${runs.length} runs found for this paper — select one:
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px">
      ${cards}
    </div>`;

  const main = document.querySelector('.main');
  const output = document.getElementById('output');
  if (main && output) main.insertBefore(wrap, output);
}

function _switchRun(run, el) {
  // Highlight selected
  document.querySelectorAll('#run-selector [onclick]').forEach(e => {
    e.style.borderColor = 'var(--border)';
    e.style.opacity = '.8';
  });
  el.style.borderColor = 'var(--blue)';
  el.style.opacity = '1';

  // Update output cards to point to the selected run
  const d = window._outputData;
  if (!d) return;
  const updated = { ...d,
    graph_html: run.graph_html || d.graph_html,
    pln_html:   run.pln_html   || d.pln_html,
    ver_html:   run.ver_html   || d.ver_html,
    run_dir:    run.run_dir    || d.run_dir,
  };
  window._outputData = updated;
  renderInspectActions(updated);
}

function discardRun() {
  document.getElementById('commit-section').style.display = 'none';
  const inspectSec = document.getElementById('inspect-section');
  if (inspectSec) inspectSec.style.display = 'none';
  const breakdown = document.getElementById('staging-breakdown');
  if (breakdown) { breakdown.style.display = 'none'; breakdown.innerHTML = ''; }
  _stagingDb = ''; _docId = '';
  AppState.clear();    // clear persisted state on discard
  const banner = document.getElementById('restore-banner');
  if (banner) banner.remove();
}

// ── View mode ─────────────────────────────────────────────────────────────────

let viewMode = 'detail';
let _totalChunks = 0;
let _startTime   = 0;
let _layerStart  = 0;
// Track actual elapsed time per completed layer for real ETA
const _layerDurations = {};   // { layerN: seconds }
let _layerStartTimes  = {};   // { layerN: Date.now() }

const LAYER_NAMES = ['','Source Registry','Deduplication','Universal Fetcher',
  'NER + Negation','Taxonomy Schema','LLM Extraction',
  'Post-Extraction Validation','Publish to KG'];

const LAYER_ICONS = ['','›1','›2','›3','›4','›5','›6','›7','›8'];

function setView(mode) {
  viewMode = mode;
  document.getElementById('view-simple').classList.toggle('active', mode==='simple');
  document.getElementById('view-detail').classList.toggle('active', mode==='detail');
  document.getElementById('simple-view').style.display  = mode==='simple' ? 'block' : 'none';
  document.getElementById('stream-view').style.display  = mode==='detail' ? 'block' : 'none';
  if (mode === 'simple') exitFullscreen();
}

function initSimpleSteps() { /* no-op — simple view now uses coffee card */ }

const COFFEE_MSGS = [
  'Analysing data sources…',
  'Checking knowledge graph…',
  'Fetching the paper…',
  'Identifying biological entities…',
  'Loading relationship taxonomy…',
  'Extracting relations with AI…',
  'Validating extracted triples…',
  'Writing to knowledge graph…',
];

// Average layer durations from real runs (seconds) — used for initial ETA before any data comes in
const _LAYER_EST = [0, 8, 25, 12, 10, 30, 15, 20, 15]; // L1–L8 rough estimates
const _TOTAL_EST = _LAYER_EST.slice(1).reduce((a,b)=>a+b,0); // ~135s total

function _simpleEls() {
  return {
    icon:   document.getElementById('coffee-title'),   // title doubles as main status
    title:  document.getElementById('coffee-title'),
    sub:    document.getElementById('coffee-sub'),
    bar:    document.getElementById('coffee-bar'),
    eta:    document.getElementById('coffee-eta'),
    stepr:  document.getElementById('coffee-step-r'),
    layMsg: document.getElementById('coffee-layer-msg'),
    stepEl: document.getElementById('coffee-step'),
    wrap:   document.getElementById('coffee-progress-wrap'),
    steam:  document.getElementById('bio-loader'),
  };
}

function initSimpleProcessing(paperLabel) {
  // Called immediately when Run is clicked — before any layer event arrives
  const e = _simpleEls();
  if (!e.title) return;
  if (e.wrap)   e.wrap.style.display   = 'block';
  if (e.steam)  e.steam.style.display  = 'flex';
  if (e.layMsg) e.layMsg.style.display = 'flex';
  e.title.textContent = 'Starting pipeline…';
  e.sub.textContent   = paperLabel
    ? `Processing "${paperLabel}" — this typically takes 2–4 minutes.`
    : 'Connecting to pipeline — this typically takes 2–4 minutes.';
  if (e.stepEl) e.stepEl.textContent = 'Initialising…';
  if (e.bar)    e.bar.style.width    = '2%';
  if (e.stepr)  e.stepr.textContent  = 'Starting…';
  if (e.eta)    e.eta.textContent    = `~${Math.ceil(_TOTAL_EST/60)}–${Math.ceil(_TOTAL_EST/60)+2} min estimated`;
}

function updateSimpleStep(n, status, message) {
  const e = _simpleEls();
  if (!e.title) return;

  if (status === 'running') {
    _layerStartTimes[n] = Date.now();
    if (e.wrap)   e.wrap.style.display   = 'block';
    if (e.steam)  e.steam.style.display  = 'flex';
    if (e.layMsg) e.layMsg.style.display = 'flex';

    e.title.textContent = _layerTitle(n);
    e.sub.textContent   = _layerHint(n);
    if (e.stepEl) e.stepEl.textContent = `Layer ${n} / 8 — ${LAYER_NAMES[n]}`;

    // Progress bar: layer start fraction
    const pct = Math.round((n - 1) / 8 * 100);
    if (e.bar) e.bar.style.width = Math.max(pct, 3) + '%';
    if (e.stepr) e.stepr.textContent = `Layer ${n} of 8`;

    // ETA: use real durations if available, else fall back to static estimates
    if (e.eta) e.eta.textContent = _calcEta(n);

  } else if (status === 'done') {
    if (_layerStartTimes[n]) _layerDurations[n] = (Date.now() - _layerStartTimes[n]) / 1000;

    const pct = Math.round(n / 8 * 100);
    if (e.bar) e.bar.style.width = pct + '%';
    if (e.stepr) e.stepr.textContent = `Layer ${n} / 8 done`;

    if (n === 8) {
      if (e.steam)  e.steam.style.display  = 'none';
      if (e.layMsg) e.layMsg.style.display = 'none';
      e.title.textContent = 'Knowledge graph ready';
      const elapsed = _startTime ? Math.round((Date.now()-_startTime)/1000) : 0;
      const elStr   = elapsed > 60 ? `${Math.floor(elapsed/60)}m ${elapsed%60}s` : `${elapsed}s`;
      e.sub.textContent   = `All 8 layers complete in ${elStr}. Review your results below.`;
      if (e.eta) e.eta.textContent = '';
    }
  }
}

function _layerTitle(n) {
  return [
    '', 'Loading paper…', 'Chunking text…', 'Resolving references…',
    'Normalising entities…', 'Extracting relations…',
    'Validating semantics…', 'Deduplicating triples…', 'Publishing to knowledge graph…',
  ][n] || 'Processing…';
}

function _layerHint(n) {
  const hints = [
    '',
    'Fetching the paper from the source database.',
    'Splitting the paper into processable chunks — larger papers take longer.',
    'Resolving co-references and pronouns across the text.',
    'Linking biological entities to standard ontologies (MESH, GO, MONDO…).',
    'Asking the LLM to extract biological relations — longest step.',
    'Checking extracted triples against the schema and taxonomy.',
    'Merging duplicate triples across chunks and prior papers.',
    'Writing Neo4j CSVs and MeTTa files to the knowledge graph.',
  ];
  return hints[n] || 'This may take a moment…';
}

function _calcEta(currentLayer) {
  const done = Object.keys(_layerDurations).map(Number);
  let secsLeft = 0;
  for (let l = currentLayer; l <= 8; l++) {
    if (_layerDurations[l]) continue; // already done
    // Use actual avg if we have data, else static estimate
    const avg = done.length > 0
      ? done.reduce((s,k)=>s+_layerDurations[k],0) / done.length
      : null;
    secsLeft += avg !== null ? avg : (_LAYER_EST[l] || 15);
  }
  if (secsLeft < 5) return '';
  return secsLeft > 90
    ? `~${Math.ceil(secsLeft/60)} min remaining`
    : `~${Math.round(secsLeft)}s remaining`;
}

// ── Stream terminal ────────────────────────────────────────────────────────────

const LAYER_COLORS = ['','--l1','--l2','--l3','--l4','--l5','--l6','--l7','--l8'];

let _currentStreamLayer = 0;

function streamHeader(layer, message) {
  const ll = document.getElementById('stream-lines');
  if (!ll) return;
  ll.querySelector('.stream-idle')?.remove();
  _currentStreamLayer = layer;

  // Update stream bar indicator
  const term = document.getElementById('stream-terminal');
  const ind  = document.getElementById('stream-layer-indicator');
  if (term) term.classList.add('active');
  if (ind) {
    ind.style.display = 'inline';
    ind.textContent   = `L${layer}`;
    ind.className     = `sl-lh-${layer}`;
  }

  const wrap = document.createElement('div');
  wrap.className  = `sl-layer-header sl-lh-${layer}`;
  wrap.id         = `slh-${layer}`;
  wrap.innerHTML = `
    <div class="lh-num" title="Layer ${layer}">${layer}</div>
    <div class="lh-name">${LAYER_ICONS[layer]} ${LAYER_NAMES[layer]}</div>
    <div class="lh-msg">${esc(message)}</div>`;
  ll.appendChild(wrap);
  ll.scrollTop = ll.scrollHeight;

  // Add/update the layer nav pill in stream bar
  let nav = document.getElementById('snav-' + layer);
  if (!nav) {
    nav = document.createElement('button');
    nav.id        = 'snav-' + layer;
    nav.className = 'stream-nav-pill';
    nav.style.cssText = `color:var(${LAYER_COLORS[layer]});border-color:var(${LAYER_COLORS[layer]});`;
    nav.textContent = layer;
    nav.title = LAYER_NAMES[layer];
    nav.onclick = () => {
      const hdr = document.getElementById('slh-' + layer);
      if (hdr) hdr.scrollIntoView({ behavior:'smooth', block:'start' });
    };
    const bar = document.querySelector('.stream-bar-title');
    if (bar) bar.appendChild(nav);
  }
}

function streamLine(message, kind) {
  const ll = document.getElementById('stream-lines');
  if (!ll) return;

  // Chunk card
  if (kind === 'chunk') {
    const parts = message.split('|');
    if (parts.length >= 4) {
      const [num, section, words, ...textParts] = parts;
      const text = textParts.join('|');
      const card = document.createElement('div');
      card.className = 'sl-chunk-card';
      card.innerHTML = `
        <span class="cc-num">#${esc(num)}</span>
        <span class="cc-section">${esc(section)}</span>
        <span class="cc-words">${esc(words)}w</span>
        <span class="cc-text">${esc(text)}</span>`;
      ll.appendChild(card);
      autoScroll(ll); return;
    }
  }

  // Step divider
  if (kind === 'step' || /^step \d/i.test(message.trim())) {
    const div = document.createElement('div');
    div.className = 'sl-step-div';
    div.textContent = message.trim();
    ll.appendChild(div);
    autoScroll(ll); return;
  }

  // Regular line
  const div = document.createElement('div');
  const cls = kind || streamClass(message);
  div.className = 'sl-' + cls;
  div.textContent = message;
  ll.appendChild(div);
  autoScroll(ll);
}

function autoScroll(el) {
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80)
    el.scrollTop = el.scrollHeight;
}

function streamClass(msg) {
  if (!msg) return 'meta';
  const m = msg.toLowerCase();
  if (m.includes('✓') || m.includes(' ok') || m.startsWith('ok') || m.includes('done') || m.includes('generated') || m.startsWith('  ✓')) return 'ok';
  if (m.includes('coref') || m.includes('rewrite') || m.includes('before :') || m.includes('after :') || m.includes('chain')) return 'coref';
  if (m.includes('entity') || m.includes('negat') || m.includes('(gene)') || m.includes('(protein)') || m.includes('absent')) return 'entity';
  if (m.includes('→') || m.includes('conf:') || m.includes('↗') || m.includes('relation')) return 'rel';
  if (m.includes('warning') || m.includes('skip') || m.includes('fail') || m.startsWith('  ✗')) return 'warn';
  if (m.startsWith('  ') && m.includes(':')) return 'meta';
  return 'plain';
}

function _applyFullscreenSize() {
  const t  = document.getElementById('stream-terminal');
  const ll = document.getElementById('stream-lines');
  if (!t || !ll) return;
  const barH = t.querySelector('.stream-bar')?.offsetHeight || 52;
  const h    = window.screen.height || window.innerHeight;
  ll.style.height = (h - barH) + 'px';
  ll.style.maxHeight = 'none';
}

function enterFullscreen() {
  const t = document.getElementById('stream-terminal');
  if (!t) return;
  const req = t.requestFullscreen || t.webkitRequestFullscreen || t.mozRequestFullScreen || t.msRequestFullscreen;
  if (req) {
    req.call(t).then(() => {
      setTimeout(_applyFullscreenSize, 100);  // after browser applies fullscreen
    }).catch(() => {
      t.classList.add('fullscreen');
      document.body.style.overflow = 'hidden';
      setTimeout(_applyFullscreenSize, 50);
    });
  } else {
    t.classList.add('fullscreen');
    document.body.style.overflow = 'hidden';
    setTimeout(_applyFullscreenSize, 50);
  }
}

function exitFullscreen() {
  const t  = document.getElementById('stream-terminal');
  const ll = document.getElementById('stream-lines');
  if (!t) return;
  const exit = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    if (exit) exit.call(document).catch(() => {});
  }
  t.classList.remove('fullscreen');
  document.body.style.overflow = '';
  // Reset inline height set by _applyFullscreenSize
  if (ll) { ll.style.height = ''; ll.style.maxHeight = ''; }
  if (viewMode === 'detail') setView('simple');
}

function toggleFullscreen() {
  const t = document.getElementById('stream-terminal');
  if (!t) return;
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    exitFullscreen();
  } else {
    enterFullscreen();
  }
}

function _onFullscreenChange() {
  const t  = document.getElementById('stream-terminal');
  const ll = document.getElementById('stream-lines');
  if (!t || !ll) return;
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    // Entered fullscreen — apply exact height
    setTimeout(_applyFullscreenSize, 80);
  } else {
    // Exited fullscreen — restore normal height
    t.classList.remove('fullscreen');
    document.body.style.overflow = '';
    ll.style.height   = '';
    ll.style.maxHeight = '';
  }
}
document.addEventListener('fullscreenchange',       _onFullscreenChange);
document.addEventListener('webkitfullscreenchange', _onFullscreenChange);

function streamHtml(html) {
  const ll = document.getElementById('stream-lines');
  if (!ll) return;
  ll.querySelector('.stream-idle')?.remove();
  const wrap = document.createElement('div');
  wrap.className = 'sl-rich-block';
  // Rich exports use inline styles — we just inject the pre block
  wrap.innerHTML = html;
  // Fix background for dark mode
  wrap.querySelectorAll('[style]').forEach(el => {
    const s = el.style;
    if (s.backgroundColor && (s.backgroundColor.includes('rgb(12') || s.backgroundColor.includes('#0c')))
      s.backgroundColor = 'transparent';
  });
  ll.appendChild(wrap);
  autoScroll(ll);
}

function clearStream() {
  const ll = document.getElementById('stream-lines');
  if (ll) ll.innerHTML = '<div class="stream-idle">Stream cleared.</div>';
}

function scrollStreamBottom() {
  const ll = document.getElementById('stream-lines');
  if (ll) ll.scrollTop = ll.scrollHeight;
}

// ── Input auto-detection ──────────────────────────────────────────────────────

function detectInput(val) {
  // User typed manually — clear chip selection
  selectedSource = '';
  document.querySelectorAll('#header-sources .sources-btn').forEach(b => b.classList.remove('active'));
  const badge = document.getElementById('detect-badge');
  const v     = val.trim();
  let type = '', label = 'Auto-detect';

  if (!v)                                            { type='';       label='Auto-detect'; }
  else if (/^PMC\d+$/i.test(v) || /^\d{5,8}$/.test(v) && v.length < 9) {
    if (/^PMC/i.test(v))                             { type='pmc';    label='PMC ID'; }
    else                                             { type='pubmed'; label='PubMed ID'; }
  }
  else if (/^10\.\d{4,}\//.test(v))                 { type='doi';    label='DOI'; }
  else if (/^https?:\/\//.test(v))                   { type='url';    label='URL'; }
  else if (v.length > 0)                             { type='pmc';    label='PMC ID'; }

  badge.textContent = label;
  badge.className   = 'detect-badge' + (type ? ' ' + type : '');
}

function showPdf() {
  document.getElementById('pdf-row').style.display = 'block';
  document.getElementById('smart-input').placeholder = 'PDF selected — or type an ID above to switch back';
  isPdf = true;
  const badge = document.getElementById('detect-badge');
  badge.textContent = 'PDF'; badge.className = 'detect-badge pdf';
  const link = document.getElementById('pdf-toggle-link');
  if (link) { link.textContent = '✕ Cancel PDF upload'; link.style.color = 'var(--red)'; }
}

function togglePdfMode() {
  if (isPdf || document.getElementById('pdf-row').style.display !== 'none') {
    clearPdf();
    const link = document.getElementById('pdf-toggle-link');
    if (link) { link.textContent = 'Upload PDF'; link.style.color = ''; }
  } else {
    showPdf();
  }
}

function onFileSelect(input) {
  if (!input.files.length) return;
  pdfFile = input.files[0];
  document.getElementById('pdf-name').textContent = pdfFile.name;
  document.getElementById('pdf-clear').style.display = 'inline';
  isPdf = true;
}

function clearPdf() {
  pdfFile = null;
  isPdf   = false;
  selectedSource = '';
  document.getElementById('pdf-input').value = '';
  document.getElementById('pdf-name').textContent = 'Click to choose PDF or drag & drop';
  document.getElementById('pdf-clear').style.display = 'none';
  document.getElementById('pdf-row').style.display = 'none';   // hide the PDF row
  const badge = document.getElementById('detect-badge');
  badge.textContent = 'Auto-detect'; badge.className = 'detect-badge';
  const inp = document.getElementById('smart-input');
  inp.placeholder = 'PMC6746067 · 25062748 · 10.1016/j.cell.2023... · https://...';
  inp.focus();
  const link = document.getElementById('pdf-toggle-link');
  if (link) { link.textContent = 'Upload PDF'; link.style.color = ''; }
}

function onDrop(e) {
  e.preventDefault();
  const f = e.dataTransfer.files[0];
  if (f && f.name.endsWith('.pdf')) {
    pdfFile = f;
    document.getElementById('pdf-name').textContent = f.name;
    document.getElementById('pdf-clear').style.display = 'inline';
    document.getElementById('drop-zone').style.color = '';
    isPdf = true;
  }
}

function setFmt(f, btn) {
  document.querySelectorAll('.fmt-chip').forEach(b => b.classList.remove('active'));
  btn.classList.add('active'); fmt = f;
  AppState.saveFormat(f);
}

// ── Sources slide-over ────────────────────────────────────────────────────────

async function openSources() {
  document.getElementById('overlay').classList.add('open');
  await loadSourcesPanel();
}

function closeSources() {
  document.getElementById('overlay').classList.remove('open');
}

async function loadSources() {
  // Load sources for header chips
  try {
    const res  = await fetch('/api/sources');
    const data = await res.json();
    renderHeaderChips(data);
  } catch(e) {}
}

function renderHeaderChips(sources) {
  const el = document.getElementById('header-sources');
  if (!el) return;
  const main = sources.filter(s => s.name !== 'pdf' && s.name !== 'www.medrxiv.org');
  // Add URL option
  const urlChip = `<button class="sources-btn" id="chip-url" onclick="quickSelectSource('url',this)">URL</button>`;
  el.innerHTML = main.map(s =>
    `<button class="sources-btn" id="chip-${esc(s.name)}" onclick="quickSelectSource('${esc(s.name)}',this)">
       ${esc(s.name)}
     </button>`
  ).join('') + urlChip;
}


function quickSelectSource(name, chipEl) {
  selectedSource = name;
  const idMap = {
    pmc:           'PMC ID — e.g. PMC6746067',
    pubmed:        'PubMed PMID — e.g. 25062748',
    geo:           'GEO accession — e.g. GSE12345678',
    clinicaltrials:'ClinicalTrials NCT ID — e.g. NCT04580043',
    biorxiv:       'bioRxiv DOI — e.g. 10.1101/2024.01.01.000001',
    url:           'Paper URL — https://www.ncbi.nlm.nih.gov/pmc/...',
  };
  const inp = document.getElementById('smart-input');
  inp.value       = '';                           // clear any previous value
  inp.placeholder = idMap[name] || `Enter ID for ${name}`;
  inp.dataset.source = name;
  inp.focus();

  const badge = document.getElementById('detect-badge');
  badge.textContent = name === 'url' ? 'URL' : name.toUpperCase();
  badge.className   = 'detect-badge ' + (name==='pmc'?'pmc':name==='pubmed'?'pubmed':name==='url'?'url':'pmc');

  document.querySelectorAll('#header-sources .sources-btn').forEach(b => b.classList.remove('active'));
  if (chipEl) chipEl.classList.add('active');
}

async function loadSourcesPanel() {
  const body = document.getElementById('so-body');
  body.innerHTML = '<div style="color:var(--text3);font-size:13px">Loading…</div>';

  // Load sources first (fast), then processed papers separately
  const srcRes  = await fetch('/api/sources');
  const sources = await srcRes.json();

  // Render sources immediately, load processed lazily
  let processed = [];
  try {
    const procRes = await fetch('/api/processed');
    processed = await procRes.json();
  } catch(e) { processed = []; }

  const srcCards = sources.map(s => `
    <div class="src-card" onclick="useSource('${esc(s.name)}')">
      <div class="src-info">
        <div class="src-name">${esc(s.name)}</div>
        <div class="src-meta">${esc((s.base_url||s.watch_dir||'file').slice(0,38))}</div>
      </div>
      <div class="src-right">
        <span class="src-fmt fmt-${s.format||'xml'}">${(s.format||'').toUpperCase()}</span>
        <span class="src-count">${s.processed_count||0} papers</span>
      </div>
      <button class="src-del" onclick="delSource(event,'${esc(s.name)}')">✕</button>
    </div>`).join('');

  const procItems = processed.slice(0,20).map(p => `
    <div class="proc-item" onclick="reuseDoc(${JSON.stringify(p.doc_id).replace(/"/g,'&quot;')},${JSON.stringify(p.source_name).replace(/"/g,'&quot;')})">
      <div class="proc-title">${esc(p.title||p.doc_id)}</div>
      <div class="proc-meta">
        <span>${esc(p.source_name)}</span>
        <span>${(p.processed_at||'').slice(0,10)}</span>
        ${p.format?`<span>${esc(p.format)}</span>`:''}
      </div>
    </div>`).join('') || '<div style="color:var(--text3);font-size:12px">No papers processed yet.</div>';

  body.innerHTML = `
    <div class="so-section-title">Registered sources</div>
    ${srcCards}
    <button class="add-btn" onclick="toggleAddForm()">＋ &nbsp; Add new source</button>
    <div class="add-form" id="add-form">
      <div class="field"><label>Name</label><input id="ns-name" placeholder="e.g. medrxiv"/></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        <div class="field"><label>Type</label>
          <select id="ns-type"><option value="api">API</option><option value="file">File</option></select>
        </div>
        <div class="field"><label>Format</label>
          <select id="ns-fmt"><option value="xml">XML</option><option value="json">JSON</option><option value="pdf">PDF</option></select>
        </div>
      </div>
      <div class="field"><label>Base URL</label><input id="ns-url" placeholder="https://api.example.org/"/></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        <div class="field"><label>ID field</label><input id="ns-id" placeholder="doi"/></div>
        <div class="field"><label>Rate limit</label><input id="ns-rate" type="number" value="5"/></div>
      </div>
      <div class="field"><label>API key env</label><input id="ns-key" placeholder="MY_API_KEY"/></div>
      <div style="display:flex;align-items:center;gap:10px;margin-top:2px">
        <button class="save-btn" onclick="saveSource()">Save source</button>
        <span class="cancel-link" onclick="toggleAddForm()">Cancel</span>
      </div>
    </div>
    <div class="so-section-title" style="margin-top:4px">Processed papers</div>
    ${procItems}
  `;
}

function toggleAddForm() {
  const f = document.getElementById('add-form');
  f.classList.toggle('open');
}

async function saveSource() {
  const fd = new FormData();
  fd.append('name',        document.getElementById('ns-name').value.trim());
  fd.append('source_type', document.getElementById('ns-type').value);
  fd.append('fmt',         document.getElementById('ns-fmt').value);
  fd.append('base_url',    document.getElementById('ns-url').value.trim());
  fd.append('id_field',    document.getElementById('ns-id').value.trim());
  fd.append('rate_limit',  document.getElementById('ns-rate').value);
  fd.append('api_key_env', document.getElementById('ns-key').value.trim());
  if (!fd.get('name')) { alert('Name is required.'); return; }
  const r = await fetch('/api/sources', { method:'POST', body:fd });
  const d = await r.json();
  if (d.error) { alert(d.error); return; }
  await loadSourcesPanel();
}

async function delSource(e, name) {
  e.stopPropagation();
  if (!confirm(`Remove "${name}"?`)) return;
  await fetch(`/api/sources/${name}`, { method:'DELETE' });
  loadSourcesPanel();
}

function useSource(name) {
  const idMap = { pmc:'PMC ID (e.g. PMC3988638)', pubmed:'PMID (e.g. 25062748)',
                  geo:'GSE ID', clinicaltrials:'NCT ID', biorxiv:'DOI' };
  document.getElementById('smart-input').placeholder = idMap[name] || 'Enter paper ID for ' + name;
  document.getElementById('smart-input').dataset.source = name;
  document.getElementById('smart-input').focus();
  closeSources();
}

function reuseDoc(docId, srcName) {
  document.getElementById('smart-input').value = docId;
  document.getElementById('smart-input').dataset.source = srcName;
  detectInput(docId);
  closeSources();
}

// ── Run ───────────────────────────────────────────────────────────────────────

let _activeSocket = null;
let _activeRunId        = null;
let _pipelineComplete   = false;
let _wsReconnectCount   = 0;

function stopPipeline() {
  // 1. Close WebSocket immediately — UI stops receiving events right away
  if (_activeSocket) {
    _activeSocket.close();
    _activeSocket = null;
  }
  // 2. Signal server to stop (fire-and-forget — don't await)
  if (_activeRunId) {
    const fd = new FormData();
    fd.append('run_id', _activeRunId);
    fetch('/api/stop', { method: 'POST', body: fd }).catch(() => {});
  }
  _activeRunId = null;
  setStatus('done', 'Stopped by user');
  setBtn(false);
  _disableStop();
  const tb = document.getElementById('test-btn');
  if (tb) tb.disabled = false;
  exitFullscreen();
  streamLine('  ⬛ Pipeline stopped by user.', 'warn');
  // Update simple view
  const _se = _simpleEls();
  if (_se.title) {
    
    _se.title.textContent = 'Pipeline incomplete';
    _se.sub.textContent   = 'Processing was stopped before completing. Please check the detailed log for the last completed step, then re-run the pipeline.';
    if (_se.steam)  _se.steam.style.display  = 'none';
    if (_se.layMsg) _se.layMsg.style.display = 'none';
    if (_se.eta)    _se.eta.textContent = 'Switch to Detailed view for the log';
    if (_se.stepr)  _se.stepr.textContent = 'Incomplete';
  }
}

function _enableStop() {
  ['stop-btn','stop-btn-main'].forEach(id => {
    const b = document.getElementById(id);
    if (!b) return;
    b.style.opacity       = '1';
    b.style.cursor        = 'pointer';
    b.style.pointerEvents = 'auto';
  });
}
function _disableStop() {
  ['stop-btn','stop-btn-main'].forEach(id => {
    const b = document.getElementById(id);
    if (!b) return;
    b.style.opacity       = '0.35';
    b.style.cursor        = 'not-allowed';
    b.style.pointerEvents = 'none';
  });
}

async function startTest() {
  resetUI();
  _startTime = Date.now(); _totalChunks = 6;
  setBtn(true);
  _enableStop();
  const tb = document.getElementById('test-btn');
  if (tb) tb.disabled = true;
  setStatus('running', 'Running mock pipeline…');
  if (viewMode === 'detail') enterFullscreen();
  const resp = await fetch('/api/run/test', { method:'POST' });
  const { run_id } = await resp.json();
  const proto = location.protocol==='https:'?'wss':'ws';
  const socket = new WebSocket(`${proto}://${location.host}/ws/${run_id}`);
  _activeSocket = socket;
  socket.onmessage = e => handle(JSON.parse(e.data));
  socket.onerror   = () => setStatus('error','Connection error');
  socket.onclose   = () => {
    setBtn(false);
    if (tb) tb.disabled = false;
    _disableStop();
    _activeSocket = null;
  };
}

async function startRun() {
  const val  = document.getElementById('smart-input').value.trim();
  const src  = document.getElementById('smart-input').dataset.source || '';

  if (!isPdf && !val) { alert('Enter a paper ID, URL, or upload a PDF.'); return; }
  if (isPdf && !pdfFile) { alert('Select a PDF file.'); return; }

  // ── Pre-run checkpoint check ────────────────────────────────────────────────
  // Works for both PMC/PubMed IDs and PDFs.
  if (!_skipCheckpointCheck) {
    try {
      let ckUrl;
      if (isPdf && pdfFile) {
        ckUrl = `/api/checkpoint-status?filename=${encodeURIComponent(pdfFile.name)}`;
      } else if (val) {
        ckUrl = `/api/checkpoint-status?doc_id=${encodeURIComponent(val)}`;
      }
      if (ckUrl) {
        const ck = await fetch(ckUrl).then(r => r.json());
        if (ck.has_checkpoint && (ck.completed_layers || []).length > 0) {
          const displayId = isPdf ? (pdfFile?.name || val) : val;
          _showPreRunLayerSelector(ck.doc_id || val, ck.completed_layers || [], ck.next_layer, displayId);
          return;
        }
      }
    } catch(e) { /* no checkpoint — proceed normally */ }
  }
  _skipCheckpointCheck = false;

  AppState.clear();                    // clear previous run state on new run
  const banner = document.getElementById('restore-banner');
  if (banner) banner.remove();
  resetUI();
  _startTime = Date.now(); _totalChunks = 0;
  setBtn(true);
  setStatus('running','Running…');
  // Immediately show "Starting…" in simple view before first layer event arrives
  const _paperLabel = isPdf ? (pdfFile?.name || 'PDF') : val;
  initSimpleProcessing(_paperLabel);
  if (viewMode === 'detail') enterFullscreen();

  const fd = new FormData();
  fd.append('output_format', fmt);
  fd.append('source_name',   src);

  if (isPdf && pdfFile) {
    fd.append('input_type',  'pdf');
    fd.append('input_value', '');
    fd.append('pdf_file',    pdfFile);
  } else {
    // If user explicitly selected a source via chip — trust that
    let type = selectedSource || src || '';
    if (!type) {
      // Auto-detect only when no source was explicitly selected
      const v = val.toUpperCase();
      type = /^PMC\d+$/.test(v)        ? 'pmc'    :
             /^\d{5,9}$/.test(val)      ? 'pubmed' :
             /^10\./.test(val)          ? 'url'    :
             /^https?:\/\//.test(val)   ? 'url'    :
             /^GSE\d+/i.test(val)       ? 'geo'    :
             /^NCT\d+/i.test(val)       ? 'clinicaltrials' :
             'pmc';
    }
    fd.append('input_type',  type);
    fd.append('input_value', val);
  }

  const resp  = await fetch('/api/run', { method:'POST', body:fd });
  const { run_id } = await resp.json();
  _activeRunId      = run_id;
  _pipelineComplete = false;
  _wsReconnectCount = 0;
  _connectWs(run_id);
}

function _connectWs(run_id) {
  const proto  = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${proto}://${location.host}/ws/${run_id}`);
  _activeSocket = socket;
  _enableStop();

  let _pingInterval = setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) socket.send('ping');
  }, 30000);

  socket.onmessage = e => handle(JSON.parse(e.data));
  socket.onerror   = () => {};   // onclose fires too — let that handle UI
  socket.onclose   = () => {
    clearInterval(_pingInterval);
    _activeSocket = null;
    if (_pipelineComplete || _activeRunId !== run_id) {
      // Normal close after completion or a new run started — clean up
      setBtn(false);
      _disableStop();
      return;
    }
    // Unexpected disconnect while pipeline is still running — reconnect
    if (_wsReconnectCount < 8) {
      _wsReconnectCount++;
      const delay = Math.min(1000 * _wsReconnectCount, 8000);
      setTimeout(() => {
        if (_activeRunId === run_id && !_pipelineComplete) {
          console.log(`[ws] reconnecting (attempt ${_wsReconnectCount})…`);
          _connectWs(run_id);
        }
      }, delay);
    } else {
      setBtn(false);
      _disableStop();
      setStatus('error', 'Connection lost — reload to check results');
    }
  };
}

// ── Event handler ─────────────────────────────────────────────────────────────

function handle(ev) {
  try { _handle(ev); } catch(e) { console.error('[handle] uncaught:', e, ev); }
}

function _handle(ev) {
  const { layer, status, message, data } = ev;

  if (layer === 0) {
    if (status === 'ping') return;  // keepalive — ignore
    const _se = _simpleEls();
    if (status === 'complete' || status === 'fatal') {
      _pipelineComplete = true;  // stop reconnect attempts
    }
    if (status === 'complete') {
      setStatus('done','Complete ✓'); exitFullscreen();
      // Simple view — complete state (layer 8 done handler also fires, this is a fallback)
      if (_se.title && _se.title.textContent !== "Knowledge graph ready") {
        const elapsed = _startTime ? Math.round((Date.now()-_startTime)/1000) : 0;
        const elStr   = elapsed > 60 ? `${Math.floor(elapsed/60)}m ${elapsed%60}s` : `${elapsed}s`;
        
        _se.title.textContent = 'Knowledge graph ready';
        _se.sub.textContent   = `Pipeline completed in ${elStr}. Review your results below.`;
        if (_se.steam)  _se.steam.style.display  = 'none';
        if (_se.layMsg) _se.layMsg.style.display = 'none';
        if (_se.bar)    _se.bar.style.width = '100%';
        if (_se.eta)    _se.eta.textContent = '';
        if (_se.stepr)  _se.stepr.textContent = '8 / 8 done';
      }
    } else {
      setStatus('error', message); exitFullscreen();
      if (_se.title) {
        
        _se.title.textContent = 'Pipeline finished with an error';
        const _errDetail = message ? message.slice(0, 120) + (message.length > 120 ? '…' : '') : '';
        _se.sub.textContent = _errDetail
          ? `Error: ${_errDetail} — Switch to Detailed view to see the full log, fix the issue, then re-run.`
          : 'An error occurred during processing. Switch to Detailed view to see what went wrong, then re-run the pipeline.';
        if (_se.steam)  _se.steam.style.display  = 'none';
        if (_se.layMsg) _se.layMsg.style.display = 'none';
        if (_se.eta)    _se.eta.textContent = '';
        if (_se.stepr)  _se.stepr.textContent = 'Failed';
      }
    }
    setBtn(false);
    _disableStop();
    _activeSocket = null;
    return;
  }

  const card  = document.getElementById('lc-'    + layer);
  const msg   = document.getElementById('lm-'    + layer);
  const stat  = document.getElementById('ls-'    + layer);
  const bar   = document.getElementById('lb-'    + layer);
  const body  = document.getElementById('lbody-' + layer);
  if (!card && !msg) return;

  card?.classList.remove('pending','running','done','error');

  if (status === 'running') {
    updateSimpleStep(layer, 'running', message);
    streamHeader(layer, message);
    if (card) {
      card.classList.add('running','open');
      if (stat) stat.textContent = 'Running';
      if (msg)  msg.innerHTML = `<span class="spinner"></span>${message}`;
      if (bar)  bar.style.width = '55%';
    }

  } else if (status === 'progress') {
    const p = data.total ? Math.round(data.done*100/data.total) : 0;
    if (bar) bar.style.width = p + '%';
    if (stat) stat.textContent = `${data.done}/${data.total}`;
    if (msg)  msg.innerHTML = `<span class="spinner"></span>${message}`;
    streamLine(`  ${message}`);
    // Capture chunk count from Layer 6 progress for time estimate
    if (layer === 6 && data.total) _totalChunks = data.total;

  } else if (status === 'log') {
    if (data.kind === 'html') {
      streamHtml(message);
    } else {
      streamLine(message, data.kind || '');
    }

  } else if (status === 'done') {
    updateSimpleStep(layer, 'done', message);
    streamLine(`  ✓ ${message}`);
    if (card) {
      card.classList.add('done');
      if (stat) stat.textContent = '✓ Done';
      if (msg)  msg.textContent  = message;
      const summary = render(layer, data);
      if (body) body.innerHTML = summary;
    }
    // Capture chunk count from Layer 3
    if (layer === 3 && data.chunks) _totalChunks = data.chunks;
    if (layer === 8) renderOutput(data);

  } else if (status === 'error') {
    updateSimpleStep(layer, 'error', message);
    streamLine(`  ✗ ERROR: ${message}`);
    if (card) {
      card.classList.add('error','open');
      if (stat) stat.textContent = 'Error';
      if (msg)  msg.textContent  = message;
      if (body) body.innerHTML   = `<div class="err-box">${esc(message)}</div>`;
    }
  }
}

// ── Renderers ─────────────────────────────────────────────────────────────────

function render(n, d) {
  return [,r1,r2,r3,r4,r5,r6,r7,r8][n]?.(d) ?? '';
}

function r1(d) {
  const chips = (d.all_sources||[]).map(s =>
    `<span class="chip"><span class="type fmt-${s.format||'xml'}">${(s.format||'').toUpperCase()}</span>${esc(s.name)}</span>`
  ).join('');
  return `
    <div class="stats">
      <div class="stat"><span class="n n-blue">${(d.all_sources||[]).length}</span> sources</div>
      <div class="stat"><span class="n n-green">${esc(d.source_name)}</span> selected</div>
    </div>
    <div class="chips" style="margin-top:10px">${chips}</div>
    <div class="info-kv"><span class="k">Doc ID:</span><code>${esc(d.doc_id)}</code></div>
    ${d.paper_url?`<div class="info-kv"><span class="k">URL:</span><a href="${esc(d.paper_url)}" target="_blank">${esc(d.paper_url.slice(0,55))}…</a></div>`:''}`;
}

function r2(d) {
  return d.already_processed
    ? `<div style="display:flex;align-items:center;gap:12px;padding:4px 0">
        <span class="dedup-warn">⚠</span>
        <div><div style="font-weight:700;color:var(--yellow)">${d.existing_triples} triples already in KG</div>
        <div style="font-size:11px;color:var(--text3);margin-top:2px">Will re-extract and update confidence scores.</div></div>
       </div>`
    : `<div style="display:flex;align-items:center;gap:12px;padding:4px 0">
        <span class="dedup-ok">✓</span>
        <div><div style="font-weight:700;color:var(--green)">New paper — not yet in KG</div>
        <div style="font-size:11px;color:var(--text3);margin-top:2px">All extracted triples will be fresh.</div></div>
       </div>`;
}

function r3(d) {
  return `<div class="stats">
    <div class="stat"><span class="n n-blue">${d.chunks}</span> chunks</div>
    <div class="stat"><span class="n n-grey">${(d.sections||[]).length}</span> sections</div>
  </div>
  <div class="info-kv" style="margin-top:8px"><span class="k">Title:</span><span class="v">${esc(d.title)}</span></div>`;
}

function r4(d) {
  const pills = (d.entities||[]).slice(0,36).map(e => {
    const cls = 't' + (e.label||'default');
    return `<span class="chip"><span class="type ${cls}">${esc(e.label||'?')}</span>${esc(e.text)}${e.negated?' <span style="color:var(--red);font-size:8px">✗</span>':''}</span>`;
  }).join('');
  return `<div class="stats">
    <div class="stat"><span class="n n-blue">${d.entity_count}</span> entities</div>
    <div class="stat"><span class="n n-red">${d.negated_count}</span> negated</div>
    <div class="stat"><span class="n n-grey">${(d.entity_types||[]).length}</span> types</div>
  </div>
  <div class="chips" style="margin-top:10px">${pills}</div>`;
}

function r5(d) {
  return `<div class="stats">
    <div class="stat"><span class="n n-blue">${d.relation_types}</span> relations</div>
    <div class="stat"><span class="n n-purple">${d.entity_types}</span> entity types</div>
  </div>
  <div class="chips" style="margin-top:10px">
    ${['BioNLP','Hetionet','OpenBioLink','BioCypher','Biolink v4.4.2'].map(s=>`<span class="chip">${s}</span>`).join('')}
  </div>`;
}

function r6(d) {
  return `<div class="stats">
    <div class="stat"><span class="n n-green">${d.viable}</span> extracted</div>
    <div class="stat"><span class="n n-grey">${d.chunks}</span> chunks</div>
    <div class="stat"><span class="n n-red">${d.rejected}</span> → human review</div>
  </div>`;
}

function r7(d) {
  const rows = (d.relations||[]).slice(0,25).map(r => {
    const vc = r.verdict==='VALID'?'valid-v':r.verdict==='DUPLICATE'?'dup-v':'flag-v';
    const cw = Math.round((r.confidence||0)*100);
    return `<tr>
      <td><span class="sub">${esc(r.subject)}</span></td>
      <td><span class="pred">${esc(r.relation)}</span></td>
      <td><span class="obj">${esc(r.object)}</span></td>
      <td><div class="cbar"><div class="ctrack"><div class="cfill" style="width:${cw}%"></div></div>${r.confidence?.toFixed(2)||'—'}</div></td>
      <td><span class="${vc}">${r.verdict||'—'}</span></td>
    </tr>`;
  }).join('');
  return `<div class="stats">
    <div class="stat"><span class="n n-green">${d.valid}</span> valid</div>
    <div class="stat"><span class="n n-grey">${d.duplicates}</span> dup</div>
    <div class="stat"><span class="n n-yellow">${d.flagged}</span> flagged</div>
    <div class="stat"><span class="n n-red">${d.contradictions}</span> conflict</div>
  </div>
  ${rows?`<div style="overflow-x:auto;margin-top:12px"><table class="rtable">
    <thead><tr><th>Subject</th><th>Relation</th><th>Object</th><th>Conf</th><th>Status</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`:''}`;
}

function r8(d) {
  const pct   = d.paper_precision != null
    ? Math.round(d.paper_precision * 100)
    : (d.ver_pct || (d.total > 0 ? Math.round(d.verified / d.total * 100) : 0));
  const color = pct>=90?'var(--green)':pct>=70?'var(--yellow)':'var(--red)';
  return `<div class="stats">
    <div class="stat"><span class="n n-green">${d.auto_insert}</span> inserted</div>
    <div class="stat"><span class="n n-yellow">${d.human_review}</span> review</div>
    <div class="stat"><span class="n" style="color:${color}">${pct}%</span> verified</div>
    <div class="stat"><span class="n n-blue">${d.neo4j_edges}</span> Neo4j edges</div>
    <div class="stat"><span class="n n-purple">${d.metta_edges}</span> MeTTa edges</div>
  </div>`;
}

// Store output data for card clicks
let _outputData = {};

function fileUrl(path) {
  if (!path) return '';
  return path.startsWith('/api/') ? path : `/api/file?path=${encodeURIComponent(path)}`;
}

let _modalSrc = '';

function openViewer(src, title) {
  _modalSrc = src;
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-frame').src = src;
  document.getElementById('file-modal').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('file-modal').classList.remove('open');
  document.getElementById('modal-frame').src = 'about:blank';
  document.body.style.overflow = '';
  document.querySelectorAll('.out-card').forEach(c => c.classList.remove('active'));
}

function openModalInTab() {
  if (_modalSrc) window.open(_modalSrc, '_blank');
}

function closeViewer() { closeModal(); }

async function loadHumanReview(runDir, stagingDb) {
  const sec = document.getElementById('review-section');
  const cards = document.getElementById('review-cards');
  if (!sec || !cards || !runDir) return;

  const resp = await fetch(`/api/human-review?run_dir=${encodeURIComponent(runDir)}`);
  const pending = await resp.json();
  if (!Array.isArray(pending) || pending.length === 0) return;

  sec.style.display = 'block';
  cards.innerHTML = pending.map((r, i) => {
    const hasTextSubj   = (r.subject_id || '').startsWith('TEXT:');
    const hasTextObj    = (r.object_id  || '').startsWith('TEXT:');
    const isTextEntity  = hasTextSubj || hasTextObj;
    const verdict = r.validation_verdict || 'REVIEW';
    const displayVerdict = (isTextEntity && verdict === 'VALID') ? 'ID?' : verdict;
    const vcolor  = displayVerdict === 'ID?' ? '#f59e0b'
                  : verdict === 'REVIEW'     ? 'var(--yellow)' : 'var(--red)';
    const vNote   = displayVerdict === 'ID?'
      ? 'Entity ID not resolved — enter a canonical ID below then approve to commit'
      : verdict === 'REVIEW'
      ? 'Uncertain — relation label may be imprecise for what the text states'
      : 'Semantic validator found a clear error — relation label does not match the text';
    const rawReason = r.review_reason || r.reasoning || '';
    const parts = rawReason.replace(/SEMANTIC_REVIEW:|SEMANTIC_REJECT:/g,'').split('|').map(s=>s.trim()).filter(Boolean);
    const whyFlagged  = parts[0] || '';
    const issuePart   = parts.find(p=>p.startsWith('Issue')) || '';
    const suggestPart = parts.find(p=>p.startsWith('Suggest')) || '';
    const fullReason  = r.reasoning || '';
    const suggestText = suggestPart.replace(/^Suggested?:\s*/i,'');
    const suggRelMatch = suggestText.match(/['"]?([A-Z][A-Z0-9_]{2,})['"]?/);
    const suggestedRelation = suggRelMatch ? suggRelMatch[1] : '';
    const recJson = JSON.stringify(r).replace(/'/g,"&#39;");
    // First card open, rest collapsed
    const bodyDisplay = i === 0 ? 'block' : 'none';
    const chevron     = i === 0 ? '▲' : '▼';
    return `<div style="background:var(--bg2);border:1px solid ${vcolor}55;border-radius:12px;margin-bottom:8px;overflow:hidden" id="rc-${i}" data-orig-rel="${esc(r.relation||'')}" data-verdict="${displayVerdict}">
      <!-- Collapsible header — always visible -->
      <div onclick="toggleReviewCard(${i})" style="display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer;user-select:none">
        <span style="color:${vcolor};font-size:10px;font-weight:700;border:1px solid ${vcolor};padding:1px 8px;border-radius:8px;flex-shrink:0">${displayVerdict}</span>
        <span style="font-size:13px;font-weight:600;color:var(--text);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
          ${esc(r.subject_name||'')} <span id="rel-display-${i}" style="color:var(--blue)">→${esc(r.relation||'')}→</span> ${esc(r.object_name||'')}
        </span>
        <span id="rc-chevron-${i}" style="color:var(--text3);font-size:11px;flex-shrink:0">${chevron}</span>
      </div>
      <!-- Collapsible body -->
      <div id="rc-body-${i}" style="display:${bodyDisplay};padding:0 16px 16px">
        <div style="font-size:11px;color:var(--text3);margin-bottom:8px">${esc(vNote)}</div>
        ${whyFlagged ? `<div style="margin-bottom:4px"><span style="color:var(--text3);font-size:10px;font-weight:600;text-transform:uppercase">Why flagged</span><div style="color:var(--text2);font-size:12px;margin-top:2px">${esc(whyFlagged)}</div></div>` : ''}
        ${issuePart  ? `<div style="margin-bottom:4px"><span style="color:var(--text3);font-size:10px;font-weight:600;text-transform:uppercase">Issue</span><div style="color:var(--text2);font-size:12px;margin-top:2px">${esc(issuePart.replace(/^Issues?:\s*/i,''))}</div></div>` : ''}
        ${suggestPart ? `<div style="margin-bottom:6px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <div><span style="color:var(--blue);font-size:10px;font-weight:600;text-transform:uppercase">Suggestion</span><div style="color:var(--blue);font-size:12px;margin-top:2px">${esc(suggestText)}</div></div>
          ${suggestedRelation ? `<button id="sugg-btn-${i}" onclick="event.stopPropagation();applySuggestion(${i},'${suggestedRelation}')"
            style="background:rgba(56,189,248,.15);border:1px solid var(--blue);border-radius:6px;padding:3px 12px;color:var(--blue);font-size:11px;cursor:pointer;font-family:var(--font);font-weight:600;white-space:nowrap;align-self:flex-end">
            ↕ Apply suggestion</button>` : ''}
        </div>` : ''}
        ${isTextEntity ? `<div style="margin-top:6px;padding:8px 10px;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:8px">
          <div style="color:#f59e0b;font-size:10px;font-weight:700;text-transform:uppercase;margin-bottom:6px">Canonical ID Correction</div>
          ${hasTextSubj ? `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">
            <span style="font-size:11px;color:var(--text3);min-width:52px">Subject:</span>
            <span style="font-size:12px;color:var(--text2)">${esc(r.subject_name||'')}</span>
            <div style="display:flex;flex-direction:column;gap:2px">
              <input id="subj-id-${i}" type="text" value="" placeholder="Looking up…"
                style="background:var(--bg3);border:1px solid #f59e0b88;border-radius:4px;padding:3px 8px;
                       color:var(--text);font-size:11px;font-family:var(--font);width:200px;outline:none"/>
              <span id="subj-id-hint-${i}" style="font-size:10px;color:var(--text3);padding-left:2px"></span>
            </div>
          </div>` : ''}
          ${hasTextObj ? `<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span style="font-size:11px;color:var(--text3);min-width:52px">Object:</span>
            <span style="font-size:12px;color:var(--text2)">${esc(r.object_name||'')}</span>
            <div style="display:flex;flex-direction:column;gap:2px">
              <input id="obj-id-${i}" type="text" value="" placeholder="Looking up…"
                style="background:var(--bg3);border:1px solid #f59e0b88;border-radius:4px;padding:3px 8px;
                       color:var(--text);font-size:11px;font-family:var(--font);width:200px;outline:none"/>
              <span id="obj-id-hint-${i}" style="font-size:10px;color:var(--text3);padding-left:2px"></span>
            </div>
          </div>` : ''}
        </div>` : ''}
        ${fullReason ? `<details style="margin-top:6px"><summary style="color:var(--text3);font-size:11px;cursor:pointer">▸ Full LLM reasoning</summary><div style="color:var(--text2);font-size:12px;font-style:italic;margin-top:4px;padding:8px;background:var(--bg3);border-radius:6px">"${esc(fullReason)}"</div></details>` : ''}
        <div style="display:flex;gap:8px;margin-top:10px">
          <button id="approve-btn-${i}" onclick="reviewAction(${i},this,'approve')" data-rec='${recJson}' data-rundir="${esc(runDir)}" data-sdb="${esc(stagingDb)}"
            style="background:rgba(34,197,94,.15);border:1px solid #22c55e;border-radius:8px;padding:6px 16px;color:#22c55e;font-size:12px;cursor:pointer;font-family:var(--font);font-weight:600">✓ Approve — add to KG</button>
          <button onclick="reviewAction(${i},this,'reject')" data-rec='${recJson}' data-rundir="${esc(runDir)}" data-sdb="${esc(stagingDb)}"
            style="background:rgba(248,113,113,.12);border:1px solid var(--red);border-radius:8px;padding:6px 16px;color:var(--red);font-size:12px;cursor:pointer;font-family:var(--font);font-weight:600">✗ Reject — discard</button>
        </div>
      </div>
    </div>`;
  }).join('');

  // Async: fetch canonical ID suggestions for TEXT: entities; auto-approve when ID? verdict + all verified
  window._cardFetchState = {};
  pending.forEach((r, i) => {
    const hasTextSubj = (r.subject_id || '').startsWith('TEXT:');
    const hasTextObj  = (r.object_id  || '').startsWith('TEXT:');
    const needed = (hasTextSubj ? 1 : 0) + (hasTextObj ? 1 : 0);
    if (needed > 0) {
      window._cardFetchState[i] = { needed, resolved: 0, allVerified: true };
      if (hasTextSubj) _fetchCanonicalId(r.subject_name || '', r.subject_type || '', i, 'subj');
      if (hasTextObj)  _fetchCanonicalId(r.object_name  || '', r.object_type  || '', i, 'obj');
    }
  });
}

async function _fetchCanonicalId(entityName, entityType, cardIdx, role) {
  const inputEl = document.getElementById(`${role}-id-${cardIdx}`);
  const hintEl  = document.getElementById(`${role}-id-hint-${cardIdx}`);
  if (!inputEl) return;
  let verified = false;
  try {
    const resp = await fetch(`/api/suggest-id?name=${encodeURIComponent(entityName)}&entity_type=${encodeURIComponent(entityType)}`);
    const data = await resp.json();
    if (data.id) {
      if (!inputEl.value || inputEl.value === '') {
        inputEl.value = data.id;
        inputEl.style.borderColor = data.verified ? '#22c55e88' : '#f59e0b88';
      }
      verified = !!data.verified;
      if (hintEl) {
        const src  = data.source ? ` · ${data.source}` : '';
        const name = data.official_name ? ` "${data.official_name}"` : '';
        if (data.verified) {
          hintEl.innerHTML = `<span style="color:#22c55e">✓ Verified${src}${name}</span>`;
        } else if (data.confidence === 'low') {
          hintEl.innerHTML = `<span style="color:var(--yellow)">⚠ LLM suggestion — verify before approving${src}</span>`;
        } else {
          hintEl.innerHTML = `<span style="color:var(--yellow)">⚠ Unverified${src}</span>`;
        }
      }
    } else {
      if (inputEl.placeholder === 'Looking up…') inputEl.placeholder = 'e.g. hgnc:1234';
      if (hintEl) hintEl.textContent = 'No suggestion — enter manually';
    }
  } catch(_) {
    if (inputEl.placeholder === 'Looking up…') inputEl.placeholder = 'e.g. hgnc:1234';
  }

  // Track completion for auto-approve
  const state = window._cardFetchState && window._cardFetchState[cardIdx];
  if (state) {
    if (!verified) state.allVerified = false;
    state.resolved++;
    const card = document.getElementById(`rc-${cardIdx}`);
    const verdict = card ? card.dataset.verdict : '';
    if (state.resolved >= state.needed) {
      if (state.allVerified && verdict === 'ID?') {
        // All canonical IDs verified, only reason was missing ID → auto-approve
        const approveBtn = document.getElementById(`approve-btn-${cardIdx}`);
        if (approveBtn) {
          approveBtn.textContent = '⟳ Auto-approving verified IDs…';
          approveBtn.style.opacity = '0.7';
          setTimeout(() => approveBtn.click(), 800);
        }
      } else if (state.allVerified) {
        // Semantic REVIEW/REJECT but IDs are now verified — update button label
        const approveBtn = document.getElementById(`approve-btn-${cardIdx}`);
        if (approveBtn) approveBtn.textContent = '✓ Approve — use suggested IDs';
      }
    }
  }
}

function _refreshVerificationCounter(verified, total) {
  if (!total) return;
  const pct = Math.round(verified / total * 100);
  const clr = pct >= 90 ? '#22c55e' : pct >= 70 ? '#eab308' : '#ef4444';
  const arc  = document.getElementById('ver-arc');
  const ring = document.getElementById('ver-pct-ring');
  const cnt  = document.getElementById('ver-count');
  const tot  = document.getElementById('ver-total');
  const bar  = document.getElementById('ver-bar');
  if (arc)  { arc.setAttribute('stroke', clr); arc.setAttribute('stroke-dasharray', `${Math.round(pct/100*138.2)} 138.2`); }
  if (ring) { ring.textContent = pct + '%'; ring.style.color = clr; }
  if (cnt)  { cnt.textContent = verified; cnt.style.color = clr; }
  if (tot)  { tot.textContent = ' / ' + total; }
  if (bar)  { bar.style.width = pct + '%'; bar.style.background = clr; }
}

function toggleReviewCard(i) {
  const body    = document.getElementById(`rc-body-${i}`);
  const chevron = document.getElementById(`rc-chevron-${i}`);
  if (!body) return;
  const open = body.style.display !== 'none';
  body.style.display    = open ? 'none' : 'block';
  if (chevron) chevron.textContent = open ? '▼' : '▲';
}

function applySuggestion(idx, suggestedRelation) {
  const card    = document.getElementById(`rc-${idx}`);
  const suggBtn = document.getElementById(`sugg-btn-${idx}`);
  const relSpan = document.getElementById(`rel-display-${idx}`);
  if (!card || !suggBtn || !relSpan) return;

  const isApplied = card.dataset.suggApplied === '1';
  const origRel   = card.dataset.origRel || '';
  const newRel    = isApplied ? origRel : suggestedRelation;

  // Patch data-rec on both Approve and Reject buttons
  card.querySelectorAll('[data-rec]').forEach(b => {
    const rec = JSON.parse(b.dataset.rec.replace(/&#39;/g,"'"));
    rec.relation = newRel;
    b.dataset.rec = JSON.stringify(rec).replace(/'/g,"&#39;");
  });

  // Update the relation display in the triple header
  relSpan.textContent = `→${newRel}→`;

  // Toggle button label and applied state
  card.dataset.suggApplied = isApplied ? '0' : '1';
  suggBtn.textContent = isApplied ? '↕ Apply suggestion' : '↩ Undo suggestion';
  suggBtn.style.background = isApplied ? 'rgba(56,189,248,.15)' : 'rgba(34,197,94,.15)';
  suggBtn.style.borderColor = isApplied ? 'var(--blue)' : '#22c55e';
  suggBtn.style.color       = isApplied ? 'var(--blue)' : '#22c55e';
}

async function reviewAction(idx, btn, action) {
  const runDir = btn.dataset.rundir;
  const sdb    = btn.dataset.sdb;
  const rec    = JSON.parse(btn.dataset.rec.replace(/&#39;/g,"'"));
  const card   = document.getElementById(`rc-${idx}`);

  // Apply any corrected canonical IDs from the TEXT: entity edit inputs
  if (action === 'approve') {
    const subjIn = document.getElementById(`subj-id-${idx}`);
    const objIn  = document.getElementById(`obj-id-${idx}`);
    if (subjIn && subjIn.value.trim()) rec.subject_id = subjIn.value.trim();
    if (objIn  && objIn.value.trim())  rec.object_id  = objIn.value.trim();
  }

  const fd = new FormData();
  fd.append('run_dir',    runDir);
  fd.append('staging_db', sdb);
  fd.append('records',    JSON.stringify([rec]));
  fd.append('action',     action);

  const resp = await fetch('/api/human-review/action', {method:'POST', body:fd});
  const d    = await resp.json();
  if (d.ok && card) {
    card.style.opacity = '0.4';
    card.style.pointerEvents = 'none';
    card.querySelector('div').insertAdjacentHTML('afterend',
      `<div style="color:${action==='approve'?'var(--green)':'var(--red)'};font-size:12px;font-weight:600;margin-top:6px">${action==='approve'?'✓ Approved — added to graph':'✗ Rejected'}</div>`);
    // Refresh staging breakdown
    if (_stagingDb) fetchStagingBreakdown(_stagingDb, _commitFormat);

    // Refresh Paper Graph and Verification cards after approve/reject.
    // Poll for real stats from the rebuilt CSV files (background rebuild takes a few seconds).
    if (_outputData && _outputData.run_dir) {
      const runDir = _outputData.run_dir;
      const bust = p => p ? p.split('?')[0] + '?t=' + Date.now() : p;
      // Poll up to 10 times (every 2s) until edge count changes
      const origEdges = _outputData.neo4j_edges || 0;
      let attempts = 0;
      const pollStats = async () => {
        attempts++;
        try {
          const sr = await fetch(`/api/run-graph-stats?run_dir=${encodeURIComponent(runDir)}`);
          const sd = await sr.json();
          if (sd.edges !== origEdges || attempts >= 10) {
            const updatedVerified = sd.total > 0 ? sd.verified : (_outputData.verified || 0);
            const updatedTotal    = sd.total > 0 ? sd.total    : (_outputData.total    || 0);
            _outputData = { ..._outputData, neo4j_edges: sd.edges || origEdges,
              neo4j_nodes: sd.nodes || _outputData.neo4j_nodes || 0,
              verified: updatedVerified, total: updatedTotal };
            // Refresh just the counter + iframes (avoid full re-render flash)
            _refreshVerificationCounter(updatedVerified, updatedTotal);
            const ts = Date.now();
            const graphFrame = document.querySelector('iframe[src*="graph"]');
            if (graphFrame && _outputData.graph_html) graphFrame.src = bust(_outputData.graph_html);
            const verFrame = document.querySelector('iframe[src*="verification"]');
            if (verFrame && _outputData.ver_html) verFrame.src = bust(_outputData.ver_html);
            return;
          }
        } catch(e) {}
        if (attempts < 10) setTimeout(pollStats, 2000);
      };
      setTimeout(pollStats, 2000); // start polling after 2s (give background thread time)
    }
  }
}

async function fetchStagingBreakdown(stagingDb, outputFormat) {
  try {
    const url = `/api/staging-info?staging_db=${encodeURIComponent(stagingDb)}&output_format=${encodeURIComponent(outputFormat||'both')}`;
    const r = await fetch(url);
    const d = await r.json();
    const el = document.getElementById('staging-breakdown');
    if (!el) return;
    const { n_staged=0, n_already=0, n_net_new=0 } = d;
    if (n_staged === 0) {
      el.innerHTML = '<span style="color:var(--text3)">No gate-passing triples in staging.</span>';
    } else if (n_already === 0) {
      el.innerHTML = `<span style="font-weight:700">${n_staged}</span> triple(s) extracted — <span style="color:var(--green);font-weight:700">all ${n_staged} are new</span> to the atomspace.`;
    } else {
      el.innerHTML =
        `<span style="font-weight:700">${n_staged}</span> triple(s) extracted from this paper:<br>` +
        `<span style="color:var(--yellow)">${n_already}</span> already in atomspace <span style="color:var(--text3)">(confidence will be updated)</span><br>` +
        `<span style="color:var(--green);font-weight:700">${n_net_new}</span> are new and will be added`;
    }
    el.style.display = 'block';
  } catch(e) {}
}

function renderInspectActions(d) {
  // Buttons removed — outputs accessible via the output cards above
}

function renderOutput(d) {
  _outputData = d;
  window.renderOutput = renderOutput;   // expose for state restore
  AppState.save(d);                     // persist to localStorage

  // ── If multiple existing runs found — show selector before output ─────────
  if (d.existing_runs && d.existing_runs.length > 1) {
    _showRunSelector(d.existing_runs, d);
  }

  // Store staging info for commit
  _stagingDb = d.staging_db || '';
  if (_stagingDb) {
    document.getElementById('commit-section').style.display = 'block';
    document.getElementById('commit-btn').disabled = false;
    document.getElementById('commit-btn').textContent = '✓ Commit to Unified KG';
    document.getElementById('commit-result').style.display = 'none';
    fetchStagingBreakdown(_stagingDb, _commitFormat);
  } else if (d.n_runs >= 1) {
    // Existing outputs loaded — no staging DB but show action buttons
    _showExistingOutputActions(d);
  }
  renderInspectActions(d);
  // Load human review triples if any
  if (d.run_dir && d.staging_db) loadHumanReview(d.run_dir, d.staging_db);
  document.getElementById('output').classList.add('show');

  // Refresh verification stats from server (verification_report.json may have been
  // updated since the pipeline ran, e.g. after human review approvals or verify_kg rebuild)
  if (d.run_dir) {
    fetch(`/api/run-graph-stats?run_dir=${encodeURIComponent(d.run_dir)}`)
      .then(r => r.json())
      .then(sd => {
        if (sd.total > 0 && (sd.verified !== (d.verified||0) || sd.total !== (d.total||0))) {
          _outputData = { ..._outputData, verified: sd.verified, total: sd.total };
          // Re-render just the inline donut/counter
          _refreshVerificationCounter(sd.verified, sd.total);
        }
      }).catch(() => {});
  }

  const cards = [];
  // Donut/bar = inline confirmation rate (verified triples against source text)
  // paper_precision is a separate accuracy metric shown only on the Neo4j card
  const pct = d.total > 0 ? Math.round(d.verified / d.total * 100) : (d.ver_pct || 0);
  const color = pct>=90?'var(--green)':pct>=70?'var(--yellow)':'var(--red)';

  // Card 1: Paper graph
  if (d.graph_html) {
    cards.push({
      icon:'◈', label:'Paper Graph',
      meta:`${d.neo4j_edges||0} edges · ${d.neo4j_nodes||0} nodes`,
      badge:'Neo4j', badgeCls:'oc-neo4j',
      src: fileUrl(d.graph_html), title:'Paper Knowledge Graph',
    });
  }

  // Card 2: Neo4j verification — show precision/recall/F1 if available
  if (d.ver_html && d.neo4j_edges > 0) {
    const prec = d.paper_precision != null ? Math.round(d.paper_precision*100)+'% P' : pct+'%';
    const rec  = d.paper_recall    != null ? Math.round(d.paper_recall*100)+'% R'    : '';
    const f1   = d.paper_f1        != null ? Math.round(d.paper_f1*100)+'% F1'       : '';
    const metaStr = [prec, rec, f1].filter(Boolean).join(' · ');
    cards.push({
      icon:'✓', label:'Neo4j Verification',
      meta: metaStr || `${pct}% confirmed`,
      badge:'Neo4j', badgeCls:'oc-neo4j',
      src: fileUrl(d.ver_html), title:'Neo4j Verification Report',
    });
  }

  // Card 3: MeTTa verification
  if (d.ver_html && d.metta_edges > 0) {
    cards.push({
      icon:'✓', label:'MeTTa Verification',
      meta:`${pct}% confirmed`,
      badge:'MeTTa', badgeCls:'oc-metta',
      src: fileUrl(d.ver_html), title:'MeTTa Verification Report',
    });
  }

  // Card: Inline verification summary
  cards.push({
    icon:'≡', label:'Inline Summary',
    meta:`${d.verified||0}/${d.total||0} triples`,
    badge:'Verify', badgeCls:'oc-verify',
    src: null, title:'Inline Verification',
    inline: true,
  });

  const cardsHtml = cards.map((c, i) => `
    <div class="out-card" id="oc-${i}" onclick="onCardClick(${i})" title="${c.inline?'Scroll to summary below':'Opens in new tab ↗'}">
      <div class="oc-icon">${c.icon}</div>
      <div class="oc-label">${c.label}</div>
      <div class="oc-meta">${c.meta}</div>
      <span class="oc-badge ${c.badgeCls}">${c.badge}${c.inline?'':' ↗'}</span>
    </div>`).join('');

  document.getElementById('out-cards').innerHTML = cardsHtml;

  // Show group labels
  if (cards.length > 0) {
    // kg-group-label removed — all cards on same row now
  }

  // PLN card — always shown (PLN is MeTTa-native, runs regardless of format)
  const plnHtml = d.pln_html || (d.run_dir ? d.run_dir.replace(/\\/g,'/') + '/pln_graph.html' : '');
  const plnSrc  = plnHtml ? fileUrl(plnHtml) : '';
  if (plnSrc && _PLN_ENABLED) {
    document.getElementById('pln-cards').innerHTML = `
      <div class="out-card pln-card" onclick="openViewer('${plnSrc}','PLN AtomSpace')"
           title="Opens PLN graph — stv values, inferred triples, contradictions ↗">
        <div class="oc-icon">🔮</div>
        <div class="oc-label">PLN AtomSpace</div>
        <div class="oc-meta">${d.pln_extracted||0} extracted · ${d.pln_inferred||0} inferred</div>
        <span class="oc-badge oc-pln">MeTTa + stv ↗</span>
      </div>`;
  } else {
    document.getElementById('pln-cards').innerHTML = '';
  }

  // Store for click handler
  window._outCards = cards;

  // Render inline verification summary
  if (d.total > 0) {
    const rows = (d.ver_results||[]).map(r => {
      const ok  = r.verified === true || r.overall_status === 'CONFIRMED';
      const rel = r.relation || r.label || '';
      // subject/object come from verify_kg.py; fallback to _name variants
      const subj = r.subject || r.subject_name || r.source_name || '';
      const obj  = r.object  || r.object_name  || r.target_name  || '';
      // Evidence: supporting sentence from sources array, or mismatch note
      const src0 = (r.sources||[])[0] || {};
      const evidence = src0.sentence || src0.note || r.supporting_text || r.mismatch_reason || '';
      return `<tr>
        <td style="color:${ok?'var(--green)':'var(--red)'};font-weight:700;text-align:center;width:24px">${ok?'✓':'✗'}</td>
        <td><span class="sub">${esc(subj)}</span></td>
        <td><span class="pred">${esc(rel)}</span></td>
        <td><span class="obj">${esc(obj)}</span></td>
        <td style="color:var(--text3);font-size:10px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            title="${esc(evidence)}">${esc(evidence.slice(0,90))}${evidence.length>90?'…':''}</td>
      </tr>`;
    }).join('');
    const vc = document.getElementById('ver-content');
    vc.style.display = 'block';
    const _pctRaw = pct;
    const _clr    = _pctRaw>=90?'var(--green)':_pctRaw>=70?'var(--yellow)':'var(--red)';
    const _clrHex = _pctRaw>=90?'#22c55e':_pctRaw>=70?'#eab308':'#ef4444';
    const _barW   = Math.round(_pctRaw);
    vc.innerHTML = `
      <div class="ver-wrap ver-collapsed" id="ver-wrap-toggle" onclick="toggleVerification(this)" title="Click to expand / collapse">
        <div style="display:flex;align-items:center;gap:16px">

          <!-- Percentage ring -->
          <div style="position:relative;flex-shrink:0;width:54px;height:54px">
            <svg width="54" height="54" viewBox="0 0 54 54">
              <circle cx="27" cy="27" r="22" fill="none" stroke="var(--bg3)" stroke-width="4"/>
              <circle id="ver-arc" cx="27" cy="27" r="22" fill="none" stroke="${_clrHex}" stroke-width="4"
                stroke-dasharray="${Math.round(_pctRaw/100*138.2)} 138.2"
                stroke-dashoffset="34.6" stroke-linecap="round"
                transform="rotate(-90 27 27)"/>
            </svg>
            <div id="ver-pct-ring" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
              font-size:12px;font-weight:800;font-family:var(--mono);color:${_clrHex}">${_pctRaw}%</div>
          </div>

          <!-- Text -->
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:3px">
              <span id="ver-count" style="color:${_clrHex}">${d.verified}</span>
              <span id="ver-total" style="color:var(--text3);font-weight:400"> / ${d.total}</span>
              &nbsp;relations confirmed against source text
            </div>
            <!-- Progress bar -->
            <div style="height:4px;background:var(--bg3);border-radius:2px;margin-bottom:5px;overflow:hidden">
              <div id="ver-bar" style="height:100%;width:${_barW}%;background:${_clrHex};border-radius:2px;transition:width .6s ease"></div>
            </div>
            <div style="font-size:10px;color:var(--text3)">Click to ${d.ver_results?.length?'see triple-level details':'collapse'}</div>
          </div>

          <span id="ver-chevron" style="color:var(--text3);font-size:11px;flex-shrink:0">▼</span>
        </div>

        <div class="ver-body" style="display:none;margin-top:14px">
          ${rows?`<table class="rtable"><thead><tr>
            <th style="width:28px"></th>
            <th>Subject</th><th>Relation</th><th>Object</th><th>Evidence</th>
          </tr></thead><tbody>${rows}</tbody></table>`:'<div style="color:var(--text3);font-size:12px;padding:8px 0">No triple-level details available.</div>'}
        </div>
      </div>`;
  }

  document.getElementById('output').scrollIntoView({ behavior:'smooth', block:'start' });
}

function toggleVerification(el) {
  const body = el.querySelector('.ver-body');
  const chev = el.querySelector('#ver-chevron');
  const isCollapsed = body.style.display === 'none';
  body.style.display = isCollapsed ? 'block' : 'none';
  if (chev) chev.textContent = isCollapsed ? '▲' : '▼';
  el.querySelector('[title]') && el.setAttribute('title', isCollapsed ? 'Click to collapse' : 'Click to expand');
}

function onCardClick(i) {
  const c = window._outCards[i];
  if (!c) return;
  document.querySelectorAll('.out-card').forEach(el => el.classList.remove('active'));
  document.getElementById('oc-'+i).classList.add('active');

  if (c.inline) {
    closeViewer();
    document.getElementById('ver-content').scrollIntoView({ behavior:'smooth', block:'start' });
    return;
  }
  if (c.src) openViewer(c.src, c.title);
}

// ── Tabs + helpers ────────────────────────────────────────────────────────────

function switchOut(pane, btn) {
  document.querySelectorAll('.otab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.opane').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('op-'+pane).classList.add('active');
}

function toggleL(n) {
  const c = document.getElementById('lc-'+n);
  c.classList.toggle('open');
}

function resetUI() {
  // Reset stream terminal
  const ll = document.getElementById('stream-lines');
  if (ll) ll.innerHTML = '<div class="stream-idle">Waiting for pipeline to start…</div>';
  // Remove layer nav pills
  for (let n=1;n<=8;n++) { document.getElementById('snav-'+n)?.remove(); }
  exitFullscreen();
  // Reset simple view card
  const _se = _simpleEls();
  
  if (_se.title)  { _se.title.textContent = 'Ready'; }
  if (_se.sub)    { _se.sub.textContent   = 'Enter a paper ID or upload a PDF'; }
  if (_se.bar)    { _se.bar.style.width   = '0%'; }
  if (_se.eta)    { _se.eta.textContent   = ''; }
  if (_se.stepr)  { _se.stepr.textContent = ''; }
  if (_se.stepEl) { _se.stepEl.textContent = ''; }
  if (_se.wrap)   { _se.wrap.style.display   = 'none'; }
  if (_se.steam)  { _se.steam.style.display  = 'none'; }
  if (_se.layMsg) { _se.layMsg.style.display = 'none'; }
  for (let n=1;n<=8;n++) {
    const c = document.getElementById('lc-'+n); if(!c)continue;
    c.className = 'lcard pending';
    const lm = document.getElementById('lm-'+n); if(lm) lm.textContent = defaultMsg(n);
    const ls = document.getElementById('ls-'+n); if(ls) ls.textContent = '—';
    const lb = document.getElementById('lbody-'+n); if(lb) lb.innerHTML = '';
    const b  = document.getElementById('lb-'+n); if(b) b.style.width='0%';
  }
  const out = document.getElementById('output');
  if (out) out.classList.remove('show');
  const commitSec = document.getElementById('commit-section');
  if (commitSec) commitSec.style.display = 'none';
  const inspectSec = document.getElementById('inspect-section');
  if (inspectSec) inspectSec.style.display = 'none';
  const reviewSec = document.getElementById('review-section');
  if (reviewSec) { reviewSec.style.display = 'none'; const rc = document.getElementById('review-cards'); if(rc) rc.innerHTML=''; }
  const breakdown = document.getElementById('staging-breakdown');
  if (breakdown) { breakdown.style.display = 'none'; breakdown.innerHTML = ''; }
  _stagingDb = ''; _docId = '';
  Object.keys(_layerDurations).forEach(k => delete _layerDurations[k]);
  Object.keys(_layerStartTimes).forEach(k => delete _layerStartTimes[k]);
  const oc = document.getElementById('out-cards');
  if (oc) oc.innerHTML = '';
  const vc = document.getElementById('ver-content');
  if (vc) { vc.style.display = 'none'; vc.innerHTML = ''; }
  window._outCards = [];
  closeModal();
}

function defaultMsg(n) {
  return ['','Resolves input and selects the correct data source',
    'Checks if this paper is already in the knowledge graph',
    'Fetches and segments the paper into text chunks',
    'Tags biological entities and detects negation',
    'Loads 87 relation types and 39 entity types',
    'Extracts structured biological relations with Pydantic enforcement',
    'Validates, deduplicates, and detects contradictions',
    'Writes triples to Neo4j CSV and MeTTa atomspace'][n];
}

function setStatus(state, text) {
  const dot  = document.getElementById('dot');
  const span = document.getElementById('status-txt');
  span.textContent  = text;
  dot.className     = 'dot' + (state==='running'?' running':state==='error'?' error':'');
}

function setBtn(disabled) { document.getElementById('run-btn').disabled = disabled; }
function toggleLogLines(n) {
  const ll  = document.getElementById('ll-' + n);
  const btn = document.querySelector(`#lt-${n} .log-toggle-btn`);
  if (!ll) return;
  const collapsed = ll.classList.toggle('collapsed');
  if (btn) btn.textContent = collapsed ? '▸ expand' : '▾ collapse';
}

function logLineClass(msg) {
  if (!msg) return 'll-meta';
  const m = msg.toLowerCase();
  if (m.startsWith('step ') || m.includes('— step'))   return 'll-step';
  if (m.includes('✓') || m.includes('ok') || m.includes('done') || m.includes('generated')) return 'll-ok';
  if (m.includes('coref') || m.includes('rewrite') || m.includes('before') || m.includes('after :')) return 'll-coref';
  if (m.includes('chunk') && (m.includes('[') || m.includes('words'))) return 'll-chunk';
  if (m.includes('entity') || m.includes('negat') || m.includes('label')) return 'll-entity';
  if (m.includes('→') || m.includes('relation') || m.includes('conf:') || m.includes('valid') || m.includes('→')) return 'll-rel';
  if (m.includes('warning') || m.includes('skip') || m.includes('error') || m.includes('fail')) return 'll-warn';
  if (m.startsWith('  ') || m.startsWith('#') || m.startsWith('─')) return 'll-meta';
  return '';
}

function esc(s) { if(!s)return''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── Init ──────────────────────────────────────────────────────────────────────
// ── Expose functions globally for inline onclick attrs (dynamically injected HTML) ──
window._commitExistingOutputs = _commitExistingOutputs;
window._commitExistingPLN     = _commitExistingPLN;
window._reprocessPaper        = _reprocessPaper;
window._switchRun             = _switchRun;
window.openViewer             = openViewer;
window.discardRun             = discardRun;
window.commitPLN              = commitPLN;
window.clearAndReset          = AppState.clearAndReset;

// ── Feature flag: PLN optional sidecar ──────────────────────────────────────
// Loaded once at page init from /api/config. Hides all PLN UI when false.
let _PLN_ENABLED = false;

function _applyPlnVisibility() {
  // index.html PLN commit step section
  const plnStep = document.getElementById('pln-commit-step');
  if (plnStep) plnStep.style.display = _PLN_ENABLED ? 'block' : 'none';
  // Any other PLN-specific elements with data-pln-feature attribute
  document.querySelectorAll('[data-pln-feature]').forEach(el => {
    el.style.display = _PLN_ENABLED ? '' : 'none';
  });
}

window.addEventListener('load', async () => {
  // Load feature flags first
  try {
    const cfg = await fetch('/api/config').then(r => r.json());
    _PLN_ENABLED = cfg.enable_pln === true;
  } catch(e) { _PLN_ENABLED = false; }
  _applyPlnVisibility();

  loadSources();
  setView('simple');   // default to simple view — detailed on demand
  const inp = document.getElementById('smart-input');
  if (inp && inp.value) detectInput(inp.value);

  // ── Restore previous session from localStorage ───────────────────────────
  if (AppState.has()) {
    const saved = AppState.load();
    AppState.showBanner();
    AppState.restore(saved);
    _applyPlnVisibility();  // re-apply after restore so PLN stays hidden when disabled
    // Refresh graph stats in case human-review approvals happened since last save
    if (saved && saved.run_dir) {
      fetch(`/api/run-graph-stats?run_dir=${encodeURIComponent(saved.run_dir)}`)
        .then(r => r.json())
        .then(sd => {
          if (sd.edges !== undefined && _outputData) {
            const ts = Date.now();
            const bust = p => p ? p.split('?')[0] + '?t=' + ts : p;
            renderOutput({
              ..._outputData,
              neo4j_edges: sd.edges,
              neo4j_nodes: sd.nodes,
              graph_html:  bust(_outputData.graph_html),
              ver_html:    bust(_outputData.ver_html),
            });
          }
        }).catch(() => {});
    }
  }
});

window.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});
