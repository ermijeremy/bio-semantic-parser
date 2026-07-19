/**
 * state.js — Frontend state persistence for Bio-Semantic Parser
 *
 * Saves pipeline run state to localStorage so the UI survives page reloads.
 * Modular design: each section of the UI has its own save/restore function.
 *
 * State structure:
 *   version      — schema version for future migrations
 *   savedAt      — ISO timestamp of last save (for expiry check)
 *   output       — pipeline output data (run_dir, graph_html, staging_db, ...)
 *   commit       — commit result and format
 *   pln          — PLN commit result
 *   log          — last N pipeline log lines (for stream replay)
 */

const STATE_KEY     = 'bio_parser_state';
const STATE_VERSION = 2;
const STATE_TTL_MS  = 12 * 60 * 60 * 1000;   // 12 hours — stale state is discarded

// ── Low-level storage ─────────────────────────────────────────────────────────

function _read() {
  try {
    const raw = localStorage.getItem(STATE_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw);
    if (s.version !== STATE_VERSION) return null;
    if (Date.now() - new Date(s.savedAt).getTime() > STATE_TTL_MS) {
      _clear(); return null;
    }
    return s;
  } catch { return null; }
}

function _write(patch) {
  try {
    const current = _read() || { version: STATE_VERSION };
    const next    = { ...current, ...patch, savedAt: new Date().toISOString() };
    localStorage.setItem(STATE_KEY, JSON.stringify(next));
  } catch (e) {
    console.warn('[state] localStorage write failed:', e.message);
  }
}

function _clear() {
  try { localStorage.removeItem(STATE_KEY); } catch {}
}

// ── Public API ────────────────────────────────────────────────────────────────

/** Save pipeline output after Layer 8 completes */
function saveOutput(data) {
  _write({ output: data, commit: null, pln: null });
}

/** Save commit result */
function saveCommit(format, result, runDirButtons) {
  _write({ commit: { format, result, runDirButtons } });
}

/** Save PLN commit result */
function savePLN(result) {
  _write({ pln: result });
}

/** Save selected output format */
function saveFormat(fmt) {
  _write({ format: fmt });
}

/** Append a log line (keeps last 200) */
function saveLogLine(line) {
  const s = _read() || { version: STATE_VERSION };
  const log = s.log || [];
  log.push(line);
  if (log.length > 200) log.splice(0, log.length - 200);
  _write({ log });
}

/** Clear all state (call on Discard or new run) */
function clearState() { _clear(); }

/** Load saved state — returns null if none or expired */
function loadState() { return _read(); }

/** Check if there's a recent saved state */
function hasState() { return _read() !== null; }

// ── UI Restore ────────────────────────────────────────────────────────────────

/**
 * Restore the full UI from saved state.
 * Called once on page load if state exists.
 * Each section is a separate function for modularity.
 */
function restoreUI(state) {
  if (!state) return;

  // Restore format selection
  if (state.format) {
    const btn = document.querySelector(`#commit-fmt-group .fmt-chip[data-fmt="${state.format}"]`);
    if (btn) {
      document.querySelectorAll('#commit-fmt-group .fmt-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    }
  }

  // Restore output section (cards, PLN card, inspect actions)
  if (state.output && window.renderOutput) {
    window.renderOutput(state.output);
  }

  // Restore commit result
  if (state.commit) {
    _restoreCommit(state.commit);
  }

  // Restore PLN result
  if (state.pln) {
    _restorePLN(state.pln);
  }

  // Restore log lines
  if (state.log && state.log.length > 0) {
    _restoreLog(state.log);
  }
}

function _restoreCommit(commit) {
  const btn = document.getElementById('commit-btn');
  const res = document.getElementById('commit-result');
  const sec = document.getElementById('commit-section');
  if (!res || !sec) return;

  sec.style.display = 'block';
  if (commit.result && commit.result.ok) {
    if (btn) { btn.disabled = true; btn.textContent = '✓ Committed'; }
    const newN = commit.result.new || 0;
    const updN = commit.result.updated || 0;
    res.style.display = 'block';
    res.innerHTML = `<div style="color:var(--green);font-size:13px;font-weight:600;margin-bottom:10px">
      ✓ ${newN} new triple(s) committed${updN > 0 ? ` · ${updN} updated` : ''} — unified ${commit.format||''} atomspace
    </div>`;
    if (commit.runDirButtons) res.innerHTML += commit.runDirButtons;
    // Show PLN step
    const plnStep = document.getElementById('pln-commit-step');
    if (plnStep) plnStep.style.display = 'block';
  }
}

function _restorePLN(pln) {
  const btn = document.getElementById('pln-commit-btn');
  const res = document.getElementById('pln-commit-result');
  if (!res) return;
  res.style.display = 'block';
  if (pln.ok) {
    if (btn) { btn.disabled = true; btn.textContent = '🔮 PLN Committed'; }
    res.innerHTML = `<div style="color:var(--pln);font-size:13px;font-weight:600">
      🔮 PLN committed — ${pln.revised||0} revised · ${pln.inferred||0} inferred · ${pln.contradictions||0} contradictions
    </div>`;
    if (pln.pln_html) {
      const fileUrl = p => `/api/file?path=${encodeURIComponent(p)}`;
      res.innerHTML += `<div style="margin-top:10px">
        <button class="fmt-chip" style="border-color:var(--pln2);color:var(--pln)"
          onclick="openViewer('${fileUrl(pln.pln_html)}','Unified PLN AtomSpace')">🔮 Unified PLN ↗</button>
      </div>`;
    }
  }
}

function _restoreLog(lines) {
  const container = document.getElementById('stream-lines');
  if (!container || !lines.length) return;
  container.innerHTML = '';
  lines.forEach(html => {
    const div = document.createElement('div');
    div.innerHTML = html;
    container.appendChild(div);
  });
  // Show the stream terminal
  const tv = document.getElementById('stream-view');
  if (tv) tv.style.display = 'block';
  container.scrollTop = container.scrollHeight;
}

// ── Banner UI ─────────────────────────────────────────────────────────────────

/** Show a "restored from previous run" banner with a Clear button */
function showRestoreBanner() {
  const state = _read();
  if (!state || !state.output) return;
  const title = state.output.title || state.output.doc_id || 'previous paper';
  const savedAt = new Date(state.savedAt).toLocaleTimeString();

  const banner = document.createElement('div');
  banner.id = 'restore-banner';
  banner.style.cssText = `
    background:var(--bg3);border:1px solid var(--border);border-radius:10px;
    padding:12px 16px;margin-bottom:16px;display:flex;align-items:center;gap:12px;
    font-size:12px;color:var(--text2);
  `;
  banner.innerHTML = `
    <span style="font-size:16px">🔁</span>
    <div style="flex:1">
      <span style="color:var(--text);font-weight:600">Restored from previous run</span>
      <span style="color:var(--text3);margin-left:8px">${escBanner(title)} · saved at ${savedAt}</span>
    </div>
    <button onclick="clearAndReset()" style="background:none;border:1px solid var(--border);
      border-radius:6px;padding:4px 12px;color:var(--text3);font-size:11px;cursor:pointer;
      font-family:var(--font)">✕ Clear</button>
  `;
  const main = document.querySelector('.main');
  if (main) main.insertBefore(banner, main.firstChild);
}

function escBanner(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/** Clear state and reload */
function clearAndReset() {
  _clear();
  location.reload();
}

// ── Exports ───────────────────────────────────────────────────────────────────

window.AppState = {
  save:        saveOutput,
  saveCommit,
  savePLN,
  saveFormat,
  saveLogLine,
  clear:       clearState,
  load:        loadState,
  has:         hasState,
  restore:     restoreUI,
  showBanner:  showRestoreBanner,
  clearAndReset,
};
