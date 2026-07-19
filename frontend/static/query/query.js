/**
 * Subgraph Query UI
 * Lets users query the committed unified KG (Neo4j or MeTTa) by selecting
 * entities, relations, and targets — then visualizes the matching subgraph.
 */

(function () {
  'use strict';
  const esc = s => String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

  let _db         = 'neo4j';
  let _network    = null;   // vis.js Network instance
  let _acTimers   = {};     // debounce timers per input

  // ── Init ──────────────────────────────────────────────────────────────────

  function initQueryPanel() {
    const panel = document.getElementById('query-panel');
    if (!panel) return;

    // DB tab switching
    panel.querySelectorAll('.query-db-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        _db = btn.dataset.db;
        panel.querySelectorAll('.query-db-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        resetQuery();
        loadEntityTypes();
      });
    });

    // Load entity types on init
    loadEntityTypes();

    // Entity 1 type change → clear entity 1 name
    document.getElementById('q-type1').addEventListener('change', () => {
      document.getElementById('q-entity1').value = '';
      document.getElementById('q-entity1-id').value = '';
      clearRelations();
      clearEntity2();
    });

    // Entity 2 type change → clear entity 2 name
    document.getElementById('q-type2').addEventListener('change', () => {
      document.getElementById('q-entity2').value = '';
      document.getElementById('q-entity2-id').value = '';
    });

    // Autocomplete for entity 1
    setupAutocomplete('q-entity1', 'q-ac1', 'q-type1', 'q-entity1-id', onEntity1Selected);

    // Autocomplete for entity 2
    setupAutocomplete('q-entity2', 'q-ac2', 'q-type2', 'q-entity2-id', null);

    // Query button
    document.getElementById('q-run-btn').addEventListener('click', runQuery);

    // Clear button
    document.getElementById('q-clear-btn').addEventListener('click', resetQuery);

    // Close autocomplete on outside click
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.query-ac-wrap')) {
        document.querySelectorAll('.query-ac-list').forEach(l => l.classList.remove('open'));
      }
    });
  }

  // ── Load entity types into dropdowns ─────────────────────────────────────

  async function loadEntityTypes() {
    try {
      const r = await fetch(`/api/query/entity-types?db=${_db}`);
      const d = await r.json();
      const types = d.types || [];
      ['q-type1', 'q-type2'].forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '<option value="">Any type</option>' +
          types.map(t => `<option value="${t}"${t === current ? ' selected' : ''}>${t}</option>`).join('');
      });
    } catch (e) { console.warn('loadEntityTypes failed', e); }
  }

  // ── Autocomplete setup ───────────────────────────────────────────────────

  function setupAutocomplete(inputId, listId, typeSelId, hiddenId, onSelect) {
    const input  = document.getElementById(inputId);
    const list   = document.getElementById(listId);
    const hidden = document.getElementById(hiddenId);
    if (!input || !list) return;

    input.addEventListener('input', () => {
      clearTimeout(_acTimers[inputId]);
      const q = input.value.trim();
      if (!q) { list.classList.remove('open'); return; }
      _acTimers[inputId] = setTimeout(() => fetchAutocomplete(q, typeSelId, list, input, hidden, onSelect), 280);
    });

    input.addEventListener('focus', () => {
      if (input.value.trim()) fetchAutocomplete(input.value.trim(), typeSelId, list, input, hidden, onSelect);
    });
  }

  async function fetchAutocomplete(q, typeSelId, list, input, hidden, onSelect) {
    const type = document.getElementById(typeSelId)?.value || '';
    try {
      const r = await fetch(`/api/query/entities?db=${_db}&q=${encodeURIComponent(q)}&type=${encodeURIComponent(type)}`);
      const d = await r.json();
      const entities = d.entities || [];
      if (!entities.length) { list.classList.remove('open'); return; }

      list.innerHTML = entities.map(e => {
        const id = esc(e.id), name = esc(e.name), type = esc(e.type);
        return `<div class="query-ac-item" data-id="${id}" data-name="${name}" data-type="${type}">
          <span>${name}</span>
          <span class="query-ac-badge">${type}</span>
          <span style="font-size:10px;color:var(--text3)">${id}</span>
        </div>`;
      }).join('');

      list.classList.add('open');

      list.querySelectorAll('.query-ac-item').forEach(item => {
        item.addEventListener('click', () => {
          input.value  = item.dataset.name;
          if (hidden) hidden.value = item.dataset.id;
          list.classList.remove('open');
          if (onSelect) onSelect(item.dataset.name, item.dataset.id, item.dataset.type);
        });
      });
    } catch (e) { console.warn('autocomplete failed', e); }
  }

  // ── After entity 1 selected → load available relations ───────────────────

  async function onEntity1Selected(name, id, type) {
    clearRelations();
    clearEntity2();
    const entity = id || name;
    try {
      const r = await fetch(`/api/query/relations?db=${_db}&entity=${encodeURIComponent(entity)}`);
      const d = await r.json();
      const rels = d.relations || [];
      const sel = document.getElementById('q-relation');
      if (!sel) return;
      sel.innerHTML = '<option value="">Any relation</option>';
      rels.forEach(rel => {
        const opt = document.createElement('option');
        opt.value = rel.relation || '';
        opt.textContent = `${String(rel.relation || '').replace(/_/g,' ')} (${rel.direction})`;
        sel.appendChild(opt);
      });
    } catch (e) { console.warn('loadRelations failed', e); }
  }

  function clearRelations() {
    const sel = document.getElementById('q-relation');
    if (sel) sel.innerHTML = '<option value="">Any relation</option>';
  }

  function clearEntity2() {
    const e2 = document.getElementById('q-entity2');
    const h2 = document.getElementById('q-entity2-id');
    if (e2) e2.value = '';
    if (h2) h2.value = '';
  }

  // ── Run query ────────────────────────────────────────────────────────────

  async function runQuery() {
    const entity1  = document.getElementById('q-entity1')?.value.trim() || '';
    const entity2  = document.getElementById('q-entity2')?.value.trim() || '';
    const relation = document.getElementById('q-relation')?.value || '';
    const btn      = document.getElementById('q-run-btn');

    if (!entity1 && !entity2 && !relation) {
      alert('Please enter at least one entity or relation to query.');
      return;
    }

    btn.disabled = true;
    btn.textContent = '⟳ Querying…';

    try {
      const params = new URLSearchParams({ db: _db });
      if (entity1)  params.set('entity1', entity1);
      if (entity2)  params.set('entity2', entity2);
      if (relation) params.set('relation', relation);

      const r = await fetch(`/api/query/subgraph?${params}`);
      const d = await r.json();

      renderSubgraph(d);
    } catch (e) {
      console.error('query failed', e);
      alert('Query failed: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '🔍 Query Subgraph';
    }
  }

  // ── Render subgraph with vis.js ──────────────────────────────────────────

  function renderSubgraph(data) {
    const result = document.getElementById('query-result');
    const meta   = document.getElementById('query-result-meta');
    const container = document.getElementById('query-graph-container');
    if (!result || !container) return;

    result.classList.add('show');

    const { nodes = [], edges = [], count = 0, db = _db } = data;

    meta.innerHTML = `<strong>${count}</strong> triple(s) found in <strong>${db.toUpperCase()}</strong> database ·
      <strong>${nodes.length}</strong> nodes · <strong>${edges.length}</strong> edges`;

    if (!nodes.length) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#6e7681;font-size:13px">No results found for this query.</div>';
      return;
    }

    // Destroy previous network
    if (_network) { _network.destroy(); _network = null; }
    container.innerHTML = '';

    // vis.js datasets
    const visNodes = new vis.DataSet(nodes);
    const visEdges = new vis.DataSet(edges);

    _network = new vis.Network(container, { nodes: visNodes, edges: visEdges }, {
      physics: {
        enabled: true,
        stabilization: { iterations: 150 },
        barnesHut: { gravitationalConstant: -8000, springLength: 120 },
      },
      interaction: { hover: true, tooltipDelay: 200 },
      edges: {
        font: { size: 10, color: '#8b949e', align: 'middle' },
        smooth: { type: 'curvedCW', roundness: 0.2 },
      },
      nodes: {
        font: { size: 13, color: '#e6edf3' },
        borderWidth: 2,
      },
    });

    // Click panel
    _network.on('click', (params) => {
      if (params.edges.length === 1) {
        const edge = visEdges.get(params.edges[0]);
        showEdgeDetail(edge);
      }
    });
  }

  function showEdgeDetail(edge) {
    const detail = document.getElementById('query-edge-detail');
    if (!detail) return;
    const from = edge.from || '';
    const to   = edge.to   || '';
    const rel  = edge._relation || edge.label || '';
    const conf = edge._confidence != null ? (edge._confidence * 100).toFixed(1) + '%' : '';
    const papers = (edge._source_papers || []).join(', ') || '—';
    const reason = edge._reasoning || '—';

    const relLabel   = esc(String(rel).replace(/_/g,' '));
    const reasonText = reason !== '—' ? esc(reason.length > 200 ? reason.slice(0,200) + '…' : reason) : '';
    detail.innerHTML = `
      <div style="font-size:12px;color:var(--text1,#e6edf3);padding:12px;background:var(--surface2,#0d1117);border-radius:8px;margin-top:12px;border:1px solid var(--border,#30363d)">
        <div style="font-weight:700;margin-bottom:8px">${esc(from)} → <span style="color:#F59E0B">${relLabel}</span> → ${esc(to)}</div>
        <div style="color:var(--text3,#6e7681);font-size:11px">Confidence: <strong style="color:var(--text1,#e6edf3)">${esc(conf)}</strong> · Papers: ${esc(papers)}</div>
        ${reasonText ? `<div style="color:var(--text3,#6e7681);font-size:11px;margin-top:6px">${reasonText}</div>` : ''}
      </div>`;
    detail.style.display = 'block';
  }

  // ── Reset ────────────────────────────────────────────────────────────────

  function resetQuery() {
    ['q-entity1', 'q-entity1-id', 'q-entity2', 'q-entity2-id'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    clearRelations();
    document.querySelectorAll('.query-ac-list').forEach(l => { l.classList.remove('open'); l.innerHTML = ''; });
    const result = document.getElementById('query-result');
    if (result) result.classList.remove('show');
    const detail = document.getElementById('query-edge-detail');
    if (detail) { detail.style.display = 'none'; detail.innerHTML = ''; }
    if (_network) { _network.destroy(); _network = null; }
  }

  // ── Auto-init when tab is switched to (called from switchTab) ───────────

  window.initQueryPanel = initQueryPanel;

  // Also expose toggle for backward compat
  window.toggleQueryPanel = function () {
    const panel = document.getElementById('query-panel');
    if (panel && !panel.dataset.init) { panel.dataset.init = '1'; initQueryPanel(); }
  };

})();
