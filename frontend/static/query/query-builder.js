/**
 * Visual Query Builder — query-builder.js
 * - Dynamic entity types from KG
 * - Type-restricted entity search (gene search only returns genes)
 * - Parameters panel with available connections per entity type
 * - Full render_html() result in iframe
 */
(function () {
  'use strict';
  const esc = s => String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

  const TYPE_STYLE = {
    GENE:{'icon':'🧬','color':'#1d4ed8','bg':'#1e3a8a'},
    PROTEIN:{'icon':'🔬','color':'#15803d','bg':'#14532d'},
    DISEASE:{'icon':'🏥','color':'#b91c1c','bg':'#7f1d1d'},
    GENOMIC_VARIANT:{'icon':'🔀','color':'#c2410c','bg':'#7c2d12'},
    DRUG:{'icon':'💊','color':'#7c3aed','bg':'#4c1d95'},
    PATHWAY:{'icon':'🔗','color':'#0369a1','bg':'#0c4a6e'},
    CELL_TYPE:{'icon':'🔵','color':'#0891b2','bg':'#164e63'},
    BIOLOGICAL_PROCESS:{'icon':'⚙️','color':'#065f46','bg':'#022c22'},
    MOLECULAR_FUNCTION:{'icon':'⚗️','color':'#0f766e','bg':'#042f2e'},
    CELLULAR_COMPONENT:{'icon':'🧫','color':'#1d4ed8','bg':'#1e3a8a'},
    PHENOTYPE:{'icon':'👁️','color':'#9a3412','bg':'#431407'},
    SMALL_MOLECULE:{'icon':'⬡','color':'#a16207','bg':'#422006'},
    TRANSCRIPTION_FACTOR_BINDING_SITE:{'icon':'📍','color':'#0f766e','bg':'#042f2e'},
    REGULATORY_REGION:{'icon':'📌','color':'#c2410c','bg':'#7c2d12'},
    ORGANISM:{'icon':'🦠','color':'#4d7c0f','bg':'#1a2e05'},
    GENOME:{'icon':'🗺️','color':'#0369a1','bg':'#0c4a6e'},
    OTHER:{'icon':'⬡','color':'#4b5563','bg':'#1f2937'},
  };
  function ts(t){ return TYPE_STYLE[t]||TYPE_STYLE.OTHER; }

  let _db='neo4j', _nodes=[], _edges=[], _network=null;
  let _drag=null, _connect=null, _nid=0, _eid=0;

  async function initBuilder(){
    bindDB();
    await loadEntityTypes();
    bindCanvas();
    document.getElementById('qb-run-btn')?.addEventListener('click', runQuery);
    document.getElementById('qb-clear-btn')?.addEventListener('click', clearCanvas);
  }

  function bindDB(){
    document.querySelectorAll('.qb-db-tab').forEach(b=>{
      b.addEventListener('click', async()=>{
        _db=b.dataset.db;
        document.querySelectorAll('.qb-db-tab').forEach(x=>x.classList.remove('active'));
        b.classList.add('active');
        await loadEntityTypes();
      });
    });
  }

  async function loadEntityTypes(){
    try{
      const r=await fetch(`/api/query/entity-types?db=${_db}`);
      const d=await r.json();
      buildPalette(d.types||[]);
    }catch(e){ console.warn('loadEntityTypes',e); }
  }

  function buildPalette(types){
    const el=document.getElementById('qb-palette-items');
    if(!el)return;
    if(!types.length){
      el.innerHTML='<div style="color:#6e7681;font-size:11px;padding:8px">No data yet.<br>Process papers first.</div>';
      return;
    }
    el.innerHTML=types.map(t=>{
      const s=ts(t);
      return `<div class="qb-etype" data-type="${t}" title="Add ${t}">
        <div class="qb-etype-dot" style="background:${s.bg}">${s.icon}</div>
        <span class="qb-etype-name">${t.replace(/_/g,' ').toLowerCase()}</span>
      </div>`;
    }).join('');
    el.querySelectorAll('.qb-etype').forEach(x=>x.addEventListener('click',()=>addNode(x.dataset.type)));
  }

  // ── Canvas ────────────────────────────────────────────────────────────────
  function bindCanvas(){
    const canvas=document.getElementById('qb-canvas'); if(!canvas)return;
    document.addEventListener('mousemove',e=>{
      if(!_drag)return;
      const n=_nodes.find(x=>x.id===_drag.nid); if(!n)return;
      n.x=e.clientX-_drag.ox; n.y=e.clientY-_drag.oy;
      const el=document.getElementById('qbn-'+n.id);
      if(el){el.style.left=n.x+'px';el.style.top=n.y+'px';}
      redrawEdges();
    });
    document.addEventListener('mouseup',e=>{
      if(_drag){document.getElementById('qbn-'+_drag.nid)?.classList.remove('selected');_drag=null;}
      if(_connect){
        canvas.style.cursor='';
        const t=e.target.closest('.qb-node');
        if(t){const tid=parseInt(t.id.replace('qbn-',''));if(tid!==_connect.fromId)openRelPicker(_connect.fromId,tid,e.clientX,e.clientY);}
        _connect=null;
      }
    });
    canvas.addEventListener('click',e=>{
      if(!e.target.closest('.qb-node')&&!e.target.closest('.qb-node-edit')&&!e.target.closest('.qb-rel-picker'))closePopups();
    });
  }

  function addNode(type){
    const canvas=document.getElementById('qb-canvas'); if(!canvas)return;
    const id=++_nid;
    const angle=(_nodes.length*80)*(Math.PI/180);
    const cx=canvas.offsetWidth/2+Math.cos(angle)*140-36;
    const cy=canvas.offsetHeight/2+Math.sin(angle)*110-36;
    const node={id,type,name:'',entityId:'',x:cx,y:cy};
    _nodes.push(node); renderNode(node,canvas); hideHint(); openNodeEdit(node);
  }

  function renderNode(node,canvas){
    const s=ts(node.type);
    const el=document.createElement('div');
    el.className='qb-node'; el.id='qbn-'+node.id;
    el.style.left=node.x+'px'; el.style.top=node.y+'px';
    el.innerHTML=`<div class="qb-node-circle" style="background:${s.bg}">
      <span style="font-size:30px;line-height:1">${s.icon}</span>
      <div class="qb-node-handle" data-nid="${node.id}" title="Click to connect to another node"></div>
    </div>
    <div class="qb-node-label" style="color:${s.color}">${node.name||node.type.replace(/_/g,' ').toLowerCase()}</div>`;

    // Drag to move
    el.addEventListener('mousedown',e=>{
      if(e.target.classList.contains('qb-node-handle'))return;
      if(e.button!==0)return;
      _drag={nid:node.id,ox:e.clientX-node.x,oy:e.clientY-node.y};
      el.classList.add('selected'); closePopups();
    });

    // Double-click node → remove it
    el.addEventListener('dblclick',e=>{
      e.stopPropagation();
      removeNode(node.id);
      closePopups();
    });

    // Click node → open edit (if not connecting)
    el.addEventListener('click',e=>{
      if(e.target.classList.contains('qb-node-handle'))return;
      if(_connect){
        // Second click: complete connection
        if(_connect.fromId!==node.id){
          openRelPicker(_connect.fromId, node.id, e.clientX, e.clientY);
        }
        _connect=null;
        document.querySelectorAll('.qb-node').forEach(n=>n.classList.remove('connecting'));
        document.getElementById('qb-canvas').style.cursor='';
        return;
      }
      openNodeEdit(node);
    });

    // Click handle → show connection picker (auto-creates target node)
    el.querySelector('.qb-node-handle').addEventListener('click',e=>{
      e.stopPropagation();
      openConnectionPicker(node.id, e.clientX, e.clientY);
    });

    canvas.appendChild(el);
  }

  function updateLabel(node){
    const el=document.getElementById('qbn-'+node.id);
    if(el)el.querySelector('.qb-node-label').textContent=node.name||node.type.replace(/_/g,' ').toLowerCase();
  }

  // ── Node edit panel — type-restricted search + available connections ───────
  async function openNodeEdit(node){
    closePopups();
    const canvas=document.getElementById('qb-canvas'); if(!canvas)return;
    const s=ts(node.type);
    const popup=document.createElement('div');
    popup.className='qb-node-edit'; popup.id='qb-node-edit-popup';
    // Use viewport (fixed) coordinates so popup is never clipped
    const rect=canvas.getBoundingClientRect();
    const vpx=Math.min(rect.left+node.x+90, window.innerWidth-270);
    const vpy=Math.max(10, Math.min(rect.top+node.y-10, window.innerHeight-400));
    popup.style.left=vpx+'px'; popup.style.top=vpy+'px';

    popup.innerHTML=`
      <!-- Header with type color -->
      <div style="background:${s.bg};padding:12px 14px;display:flex;align-items:center;gap:10px">
        <div style="width:34px;height:34px;border-radius:50%;background:rgba(0,0,0,.25);
          display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0">${s.icon}</div>
        <div>
          <div style="font-size:13px;font-weight:700;color:#fff">${node.type.replace(/_/g,' ').toLowerCase()} parameters</div>
        </div>
      </div>
      <!-- Body -->
      <div style="padding:12px 14px">
        <div style="font-size:10px;font-weight:700;color:#6e7681;text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px">Name or ID</div>
        <div style="position:relative">
          <input type="text" id="qb-ne-input" value="${node.name}"
            placeholder="Search ${node.type.replace(/_/g,' ').toLowerCase()}…"
            autocomplete="off" style="width:100%;box-sizing:border-box;
            background:#0d1117;border:1px solid rgba(255,255,255,.15);border-radius:8px;
            color:#e6edf3;font-size:14px;padding:10px 12px;outline:none;
            transition:border-color .15s"
            onfocus="this.style.borderColor='#58a6ff'"
            onblur="this.style.borderColor='rgba(255,255,255,.15)'">
          <div id="qb-ne-ac" style="position:absolute;top:100%;left:0;right:0;background:#161b22;
            border:1px solid #1f6feb;border-top:none;border-radius:0 0 8px 8px;
            max-height:160px;overflow-y:auto;z-index:100;display:none"></div>
        </div>

        <!-- Available connections -->
        <div id="qb-ne-connections" style="margin-top:12px;display:none">
          <div style="font-size:10px;font-weight:700;color:#6e7681;text-transform:uppercase;
            letter-spacing:.5px;margin-bottom:8px">Available connections</div>
          <div id="qb-ne-conn-list"></div>
        </div>

        <div style="display:flex;gap:6px;margin-top:12px">
          <button class="qb-node-edit-btn qb-node-edit-ok" style="
            flex:1;padding:8px;border-radius:8px;background:${s.bg};color:#fff;
            border:1px solid ${s.color};font-size:12px;font-weight:600;cursor:pointer">✓ Set</button>
          <button class="qb-node-edit-btn qb-node-edit-del" style="
            padding:8px 10px;border-radius:8px;background:transparent;
            border:1px solid rgba(248,81,73,.4);color:#f85149;font-size:12px;cursor:pointer">✕</button>
        </div>
      </div>`;
    canvas.appendChild(popup);

    // Load available connections for this entity type
    loadTypeConnections(node.type, node.id);

    const input=popup.querySelector('#qb-ne-input');
    const acList=popup.querySelector('#qb-ne-ac');
    input.focus(); input.select();

    let timer;
    input.addEventListener('input',()=>{
      clearTimeout(timer);
      const q=input.value.trim();
      if(!q){acList.style.display='none';return;}
      timer=setTimeout(async()=>{
        try{
          // TYPE-RESTRICTED search — always pass entity type
          const r=await fetch(`/api/query/entities?db=${_db}&q=${encodeURIComponent(q)}&type=${encodeURIComponent(node.type)}`);
          const d=await r.json();
          const items=d.entities||[];
          if(!items.length){acList.style.display='none';return;}
          acList.innerHTML=items.map(e=>{
            const name=esc(e.name), id=esc(e.id);
            return `<div data-name="${name}" data-id="${id}"
              style="padding:9px 12px;font-size:13px;color:#e6edf3;cursor:pointer;
              display:flex;align-items:center;gap:8px;border-bottom:1px solid #21262d;
              user-select:none;-webkit-user-select:none">
              <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${name}</span>
              <span style="font-size:10px;color:#6e7681;background:#1f6feb22;padding:2px 6px;
                border-radius:4px;white-space:nowrap;flex-shrink:0">${id}</span>
            </div>`;
          }).join('');
          // Position autocomplete using fixed coords so it's never clipped
          const inputRect=input.getBoundingClientRect();
          acList.style.position='fixed';
          acList.style.left=inputRect.left+'px';
          acList.style.top=(inputRect.bottom+2)+'px';
          acList.style.width=inputRect.width+'px';
          acList.style.maxHeight='200px';
          acList.style.overflowY='auto';
          acList.style.zIndex='99999';
          acList.style.display='block';

          let _selecting=false;
          acList.querySelectorAll('div').forEach(item=>{
            item.style.cursor='pointer';
            item.addEventListener('mouseenter',()=>item.style.background='#21262d');
            item.addEventListener('mouseleave',()=>item.style.background='');

            function selectItem(){
              if(_selecting)return; _selecting=true;
              const name=item.getAttribute('data-name')||item.dataset.name||'';
              const id=item.getAttribute('data-id')||item.dataset.id||'';
              if(!name)return;
              input.value=name;
              node.name=name;
              node.entityId=id;
              acList.style.display='none';
              updateLabel(node);
              loadEntityConnections(name, node.type, node.id);
              setTimeout(()=>_selecting=false, 300);
            }

            item.addEventListener('mousedown',(ev)=>{ ev.preventDefault(); selectItem(); });
            item.addEventListener('click',(ev)=>{ ev.stopPropagation(); selectItem(); });
            item.addEventListener('touchend',(ev)=>{ ev.preventDefault(); selectItem(); });
          });
        }catch(e){}
      },250);
    });

    function confirmNodeEdit(){
      const val=input.value.trim();
      if(val) node.name=val;
      updateLabel(node);
      closePopups();
    }
    popup.querySelector('.qb-node-edit-ok').addEventListener('click', confirmNodeEdit);
    input.addEventListener('keydown',e=>{
      if(e.key==='Enter'){ e.preventDefault(); confirmNodeEdit(); }
      if(e.key==='Escape') closePopups();
    });
    // Auto-save on blur if something typed
    input.addEventListener('blur',()=>{
      const val=input.value.trim();
      if(val && !node.name) { node.name=val; updateLabel(node); }
    });
    popup.querySelector('.qb-node-edit-del').addEventListener('click',()=>{removeNode(node.id);closePopups();});
  }

  // Load available connections for an entity TYPE (schema-level)
  async function loadTypeConnections(entityType, fromNodeId){
    try{
      const r=await fetch(`/api/query/type-connections?db=${_db}&entity_type=${encodeURIComponent(entityType)}`);
      const d=await r.json();
      renderConnections(d.connections||[], fromNodeId);
    }catch(e){}
  }

  async function loadEntityConnections(entityName, entityType, fromNodeId){
    try{
      const r=await fetch(`/api/query/type-connections?db=${_db}&entity_type=${encodeURIComponent(entityType)}`);
      const d=await r.json();
      renderConnections(d.connections||[], fromNodeId);
    }catch(e){}
  }

  function renderConnections(connections, fromNodeId){
    const wrap=document.getElementById('qb-ne-connections');
    const list=document.getElementById('qb-ne-conn-list');
    if(!wrap||!list||!connections.length)return;
    wrap.style.display='block';
    list.innerHTML=connections.slice(0,6).map((c,idx)=>{
      const s=c.target_type?ts(c.target_type):null;
      const dirIcon=c.direction==='incoming'?'←':'→';
      return `<div class="qb-conn-clickable" data-idx="${idx}"
        style="display:flex;align-items:center;gap:10px;padding:8px 10px;
        border-radius:8px;margin-bottom:4px;cursor:pointer;
        background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
        transition:background .12s;user-select:none"
        onmouseover="this.style.background='rgba(88,166,255,.12)';this.style.borderColor='rgba(88,166,255,.3)'"
        onmouseout="this.style.background='rgba(255,255,255,.04)';this.style.borderColor='rgba(255,255,255,.07)'"
        title="Click → creates a ${(c.target_type||'entity').toLowerCase()} node connected via ${c.relation}">
        ${s?`<div style="width:28px;height:28px;border-radius:50%;background:${s.bg};
          display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0">${s.icon}</div>`
         :`<div style="width:28px;height:28px;border-radius:50%;background:#1f2937;
          display:flex;align-items:center;justify-content:center;font-size:11px;flex-shrink:0">⬡</div>`}
        ${c.target_type?`<span style="font-size:11px;color:#94A3B8;white-space:nowrap">${c.target_type.replace(/_/g,' ').toLowerCase()}</span>`:''}
        <span style="color:rgba(255,255,255,.3);font-size:13px">${dirIcon}</span>
        <span style="font-size:11px;color:#e6edf3;flex:1;font-weight:500">${c.relation.replace(/_/g,' ')}</span>
        ${c.count?`<span style="font-size:9px;color:#3fb950;opacity:.7">${c.count}×</span>`:''}
        <span style="font-size:10px;color:#58a6ff;opacity:.7">+</span>
      </div>`;
    }).join('');

    // Attach click handlers to create connected node + edge
    list.querySelectorAll('.qb-conn-clickable').forEach((el,idx)=>{
      const c=connections[idx];
      function onConnClick(ev){
        ev.stopPropagation(); ev.preventDefault();
        const fromNode=_nodes.find(n=>n.id===fromNodeId);
        if(!fromNode)return;
        const canvas=document.getElementById('qb-canvas'); if(!canvas)return;
        // Create target node
        const newNode={id:++_nid,type:c.target_type||'OTHER',name:'',entityId:'',
          x:fromNode.x+200, y:fromNode.y+80};
        _nodes.push(newNode); renderNode(newNode, canvas);
        // Create edge
        _edges.push({id:++_eid, from:c.direction==='incoming'?newNode.id:fromNode.id,
                     to:c.direction==='incoming'?fromNode.id:newNode.id, relation:c.relation});
        redrawEdges(); hideHint(); closePopups();
        // Open new node edit immediately
        setTimeout(()=>openNodeEdit(newNode), 80);
      }
      el.addEventListener('mousedown',(ev)=>{ ev.preventDefault(); onConnClick(ev); });
      el.addEventListener('click', onConnClick);
    });
  }

  function removeNode(nid){
    _nodes=_nodes.filter(n=>n.id!==nid); _edges=_edges.filter(e=>e.from!==nid&&e.to!==nid);
    document.getElementById('qbn-'+nid)?.remove(); redrawEdges();
    if(_nodes.length===0)showHint();
  }

  // ── Connection picker — shows relation + target type, auto-creates target node ──
  async function openConnectionPicker(fromId, cx, cy){
    closePopups();
    const canvas=document.getElementById('qb-canvas'); if(!canvas)return;
    const rect=canvas.getBoundingClientRect();
    const fromNode=_nodes.find(n=>n.id===fromId); if(!fromNode)return;

    // Load connections for this entity (instance-level if name known, type-level otherwise)
    let connections=[];
    if(fromNode.name){
      try{
        const r=await fetch(`/api/query/type-connections?db=${_db}&entity_type=${encodeURIComponent(fromNode.type)}`);
        const d=await r.json(); connections=d.connections||[];
      }catch(e){}
    } else {
      try{
        const r=await fetch(`/api/query/type-connections?db=${_db}&entity_type=${encodeURIComponent(fromNode.type)}`);
        const d=await r.json(); connections=d.connections||[];
      }catch(e){}
    }

    const picker=document.createElement('div');
    picker.className='qb-rel-picker'; picker.id='qb-rel-picker';
    picker.style.position='fixed';
    picker.style.zIndex='99999';
    picker.style.width='260px';
    const px=Math.min(cx+20, window.innerWidth-270);
    picker.style.left=px+'px';
    picker.style.top=Math.max(10, Math.min(cy-20, window.innerHeight-350))+'px';

    const s=ts(fromNode.type);
    picker.innerHTML=`
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #30363d">
        <span style="font-size:14px">${s.icon}</span>
        <span style="font-size:11px;font-weight:700;color:#e6edf3">Available connections from ${fromNode.type.replace(/_/g,' ').toLowerCase()}</span>
      </div>
      ${connections.length ? connections.slice(0,8).map(c=>{
        const ts2=ts(c.target_type||'OTHER');
        return `<div class="qb-conn-item" data-rel="${c.relation}" data-target="${c.target_type||''}" data-dir="${c.direction||'outgoing'}"
          style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;
          margin-bottom:3px;cursor:pointer;background:rgba(255,255,255,.03);
          border:1px solid rgba(255,255,255,.06)"
          onmouseover="this.style.background='rgba(255,255,255,.08)'"
          onmouseout="this.style.background='rgba(255,255,255,.03)'">
          <div style="width:26px;height:26px;border-radius:50%;background:${ts2.bg};
            display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0">${ts2.icon}</div>
          <div style="flex:1;min-width:0">
            <div style="font-size:12px;color:#e6edf3;font-weight:500">${c.relation.replace(/_/g,' ')}</div>
            <div style="font-size:10px;color:#6e7681">${(c.target_type||'any').replace(/_/g,' ').toLowerCase()} · ${c.count||0}×</div>
          </div>
          <span style="font-size:10px;color:#F59E0B">${c.direction==='incoming'?'←':'→'}</span>
        </div>`;
      }).join('')
      : '<div style="color:#6e7681;font-size:12px;padding:8px">No connections found.<br>Add more papers to the KG first.</div>'}
      <div style="margin-top:8px;padding-top:8px;border-top:1px solid #30363d">
        <div class="qb-conn-item" data-rel="" data-target="" data-dir="outgoing"
          style="display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:6px;
          cursor:pointer;color:#6e7681;font-size:11px"
          onmouseover="this.style.color='#e6edf3'"
          onmouseout="this.style.color='#6e7681'">
          <span>⬡</span> Any entity / Any relationship
        </div>
      </div>`;

    canvas.appendChild(picker);

    picker.querySelectorAll('.qb-conn-item').forEach(item=>{
      item.addEventListener('click',()=>{
        const relation=item.dataset.rel;
        const targetType=item.dataset.target||'OTHER';
        closePopups();
        // Auto-create target node with correct type
        const fromEl=document.getElementById('qbn-'+fromId);
        const targetX=(fromNode.x||100)+180;
        const targetY=fromNode.y||100;
        const newNode={id:++_nid,type:targetType,name:'',entityId:'',x:targetX,y:targetY};
        _nodes.push(newNode);
        renderNode(newNode, canvas);
        hideHint();
        // Add edge
        _edges.push({id:++_eid,from:fromId,to:newNode.id,relation:relation});
        redrawEdges();
        // Open edit for new node immediately
        setTimeout(()=>openNodeEdit(newNode), 100);
      });
    });
  }

  // Keep openRelPicker as alias for backward compat (between 2 existing nodes)
  async function openRelPicker(fromId,toId,cx,cy){
    closePopups();
    const canvas=document.getElementById('qb-canvas'); if(!canvas)return;
    const fromNode=_nodes.find(n=>n.id===fromId);
    const toNode=_nodes.find(n=>n.id===toId);
    let connections=[];
    if(fromNode?.type){
      try{const r=await fetch(`/api/query/type-connections?db=${_db}&entity_type=${encodeURIComponent(fromNode.type)}`);const d=await r.json();connections=d.connections||[];}catch(e){}
    }
    const picker=document.createElement('div');
    picker.className='qb-rel-picker'; picker.id='qb-rel-picker';
    const rect=canvas.getBoundingClientRect();
    picker.style.left=Math.min(cx-rect.left,canvas.offsetWidth-230)+'px';
    picker.style.top=(cy-rect.top)+'px';
    picker.innerHTML=`<div class="qb-rel-picker-title">Select relationship</div>
      <div class="qb-rel-item" data-rel="">— Any relationship</div>
      ${connections.map(c=>`<div class="qb-rel-item" data-rel="${c.relation}">
        ${c.relation.replace(/_/g,' ')}
        <span style="font-size:10px;color:#6e7681;margin-left:auto">${c.direction||''}</span>
      </div>`).join('')}`;
    canvas.appendChild(picker);
    picker.querySelectorAll('.qb-rel-item').forEach(item=>item.addEventListener('click',()=>{
      _edges.push({id:++_eid,from:fromId,to:toId,relation:item.dataset.rel});
      redrawEdges(); closePopups();
    }));
  }

  // ── SVG edges ─────────────────────────────────────────────────────────────
  function redrawEdges(){
    const svg=document.getElementById('qb-svg'); if(!svg)return;
    svg.innerHTML=`<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#58a6ff"/></marker></defs>`;
    _edges.forEach(edge=>{
      const fn=_nodes.find(n=>n.id===edge.from),tn=_nodes.find(n=>n.id===edge.to);
      if(!fn||!tn)return;
      const x1=fn.x+36,y1=fn.y+36,x2=tn.x+36,y2=tn.y+36;
      const cx1=(x1+x2)/2-(y2-y1)*0.25,cy1=(y1+y2)/2+(x2-x1)*0.25;
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');
      path.setAttribute('d',`M${x1},${y1} Q${cx1},${cy1} ${x2},${y2}`);
      path.setAttribute('class','qb-edge-line'); path.setAttribute('marker-end','url(#arrow)');
      svg.appendChild(path);
      const label=edge.relation?edge.relation.replace(/_/g,' '):'—';
      const g=document.createElementNS('http://www.w3.org/2000/svg','g');
      g.style.cursor='pointer';
      g.setAttribute('title','Click to remove');
      const bg=document.createElementNS('http://www.w3.org/2000/svg','rect');
      const tw=label.length*6.5+20;
      bg.setAttribute('x',cx1-tw/2); bg.setAttribute('y',cy1-22);
      bg.setAttribute('width',tw); bg.setAttribute('height',18);
      bg.setAttribute('rx','5'); bg.setAttribute('fill','#1c2333');
      bg.setAttribute('stroke','#F59E0B'); bg.setAttribute('stroke-width','1');
      const text=document.createElementNS('http://www.w3.org/2000/svg','text');
      text.setAttribute('x',cx1); text.setAttribute('y',cy1-9);
      text.setAttribute('class','qb-edge-label'); text.textContent=label;
      const del=document.createElementNS('http://www.w3.org/2000/svg','text');
      del.setAttribute('x',cx1+tw/2-8); del.setAttribute('y',cy1-10);
      del.setAttribute('fill','#f85149'); del.setAttribute('font-size','11');
      del.setAttribute('font-family','sans-serif'); del.textContent='✕';
      g.appendChild(bg); g.appendChild(text); g.appendChild(del);
      g.addEventListener('click',()=>{ _edges=_edges.filter(e2=>e2.id!==edge.id); redrawEdges(); });
      svg.appendChild(g);
    });
  }

  // ── Run query — pass type filters ─────────────────────────────────────────
  async function runQuery(){
    const btn=document.getElementById('qb-run-btn');
    if(!_nodes.length){alert('Add at least one entity to the canvas first.');return;}
    btn.disabled=true; btn.textContent='⟳ Querying…';

    const params=new URLSearchParams({db:_db,limit:'150'});
    // Pass ALL node names and ALL edge relations — backend finds subgraph touching any of them
    const namedNodes=_nodes.filter(n=>n.name);
    const relations=[..._edges.map(e=>e.relation).filter(Boolean)];
    if(namedNodes[0]) { params.set('entity1', namedNodes[0].name); params.set('type1', namedNodes[0].type); }
    if(namedNodes[1]) { params.set('entity2', namedNodes[1].name); params.set('type2', namedNodes[1].type); }
    // For 3+ nodes: pass as extra entities (backend returns union of all connections)
    namedNodes.slice(2).forEach((n,i)=>params.append('entity_extra', n.name));
    if(relations[0]) params.set('relation', relations[0]);

    const result=document.getElementById('qb-result');
    const frame=document.getElementById('qb-result-frame');
    const meta=document.getElementById('qb-result-meta');

    try{
      frame.src=`/api/query/subgraph-html?${params}`;
      result.classList.add('show');
      if(meta) meta.innerHTML=`DB: <strong>${_db.toUpperCase()}</strong> &nbsp;·&nbsp;
        ${_nodes.map(n=>`<span style="color:${ts(n.type).color}">${n.name||n.type}</span>`).join(' → ')}
        <button onclick="window.open('/api/query/subgraph-html?${params}','_blank')"
          style="margin-left:12px;padding:4px 10px;background:transparent;border:1px solid var(--border,#30363d);
          border-radius:5px;color:var(--text2,#8b949e);font-size:11px;cursor:pointer">↗ Full screen</button>`;
      result.scrollIntoView({behavior:'smooth',block:'start'});
    }catch(e){ alert('Query failed: '+e.message); }
    finally{ btn.disabled=false; btn.textContent='▶ Run Query'; }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function closePopups(){
    document.getElementById('qb-node-edit-popup')?.remove();
    document.getElementById('qb-rel-picker')?.remove();
  }
  function clearCanvas(){
    _nodes=[];_edges=[];_nid=0;_eid=0;
    const c=document.getElementById('qb-canvas');
    if(c)c.querySelectorAll('.qb-node,.qb-node-edit,.qb-rel-picker').forEach(el=>el.remove());
    redrawEdges();showHint();
    document.getElementById('qb-result')?.classList.remove('show');
    if(_network){_network.destroy();_network=null;}
  }
  function showHint(){const h=document.getElementById('qb-canvas-hint');if(h)h.style.display='';}
  function hideHint(){const h=document.getElementById('qb-canvas-hint');if(h)h.style.display='none';}

  function showConnectHint(){
    const hint=document.getElementById('qb-canvas-hint');
    if(!hint)return;
    hint.style.display='';
    hint.innerHTML=`<div style="font-size:32px;margin-bottom:8px">🔗</div>
      <div style="font-size:13px;font-weight:600;color:#58a6ff">Now click another node</div>
      <div style="font-size:11px;margin-top:4px">to connect them</div>
      <button onclick="cancelConnect()" style="margin-top:12px;padding:4px 12px;background:transparent;
        border:1px solid #30363d;border-radius:6px;color:#6e7681;font-size:11px;cursor:pointer">Cancel</button>`;
  }

  window.cancelConnect=function(){
    _connect=null;
    document.querySelectorAll('.qb-node').forEach(n=>n.classList.remove('connecting'));
    document.getElementById('qb-canvas').style.cursor='';
    if(_nodes.length) hideHint(); else showHint();
  };

  window.initQueryBuilder=initBuilder;
})();
