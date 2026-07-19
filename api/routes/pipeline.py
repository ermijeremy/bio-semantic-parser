"""Routes: /api/run, /api/run/test, /api/stop, /ws/{run_id}."""
import asyncio
import json
import shutil
import sys
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from api.run_state import _connections, _queues, _stop_flags

_ROOT = Path(__file__).resolve().parents[2]

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

router = APIRouter()


@router.get("/api/test/graph")
async def test_graph_html():
    return HTMLResponse(_sample_graph_html())


@router.get("/api/test/verify")
async def test_verify_html():
    return HTMLResponse(_sample_verify_html())


def _sample_graph_html():
    return """<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Knowledge Graph — Test</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
body{margin:0;background:#0d1117;font-family:Inter,sans-serif}
#graph{width:100%;height:100vh}
#info{position:fixed;top:16px;left:16px;background:#161b22;border:1px solid #30363d;
  padding:12px 16px;border-radius:10px;color:#e6edf3;font-size:12px}
</style></head><body>
<div id="info">🧬 Knowledge Graph — Mock Test Run<br><span style="color:#8b949e">35 nodes · 28 edges · 94% verified</span></div>
<div id="graph"></div>
<script>
const nodes = new vis.DataSet([
  {id:1,label:'rapamycin',color:{background:'#fb923c',border:'#ea580c'},font:{color:'#fff'},shape:'ellipse'},
  {id:2,label:'mTOR',color:{background:'#4f9cf9',border:'#2563eb'},font:{color:'#fff'},shape:'ellipse'},
  {id:3,label:'autophagy',color:{background:'#34d399',border:'#059669'},font:{color:'#fff'},shape:'ellipse'},
  {id:4,label:'BRCA1',color:{background:'#4f9cf9',border:'#2563eb'},font:{color:'#fff'},shape:'ellipse'},
  {id:5,label:'breast cancer',color:{background:'#f87171',border:'#dc2626'},font:{color:'#fff'},shape:'ellipse'},
  {id:6,label:'p53',color:{background:'#a78bfa',border:'#7c3aed'},font:{color:'#fff'},shape:'ellipse'},
  {id:7,label:'apoptosis',color:{background:'#34d399',border:'#059669'},font:{color:'#fff'},shape:'ellipse'},
  {id:8,label:'Mus musculus',color:{background:'#fbbf24',border:'#d97706'},font:{color:'#fff'},shape:'ellipse'},
  {id:9,label:'FOXO3',color:{background:'#4f9cf9',border:'#2563eb'},font:{color:'#fff'},shape:'ellipse'},
  {id:10,label:'lifespan',color:{background:'#34d399',border:'#059669'},font:{color:'#fff'},shape:'ellipse'},
]);
const edges = new vis.DataSet([
  {from:1,to:2,label:'inhibits',color:{color:'#f87171'},arrows:'to',font:{color:'#8b949e',size:10}},
  {from:2,to:3,label:'regulates',color:{color:'#6b8cbe'},arrows:'to',font:{color:'#8b949e',size:10}},
  {from:4,to:5,label:'associates_with',color:{color:'#6b8cbe'},arrows:'to',font:{color:'#8b949e',size:10}},
  {from:6,to:7,label:'activates',color:{color:'#34d399'},arrows:'to',font:{color:'#8b949e',size:10}},
  {from:1,to:8,label:'extends_lifespan',color:{color:'#34d399'},arrows:'to',font:{color:'#8b949e',size:10}},
  {from:9,to:10,label:'extends_lifespan',color:{color:'#34d399'},arrows:'to',font:{color:'#8b949e',size:10}},
  {from:1,to:9,label:'upregulates',color:{color:'#34d399'},arrows:'to',font:{color:'#8b949e',size:10}},
]);
const container = document.getElementById('graph');
const network = new vis.Network(container, {nodes,edges}, {
  background:'#0d1117',
  nodes:{borderWidth:2,shadow:true,font:{size:12}},
  edges:{width:1.5,shadow:true,smooth:{type:'curvedCW',roundness:.2}},
  physics:{stabilization:{iterations:100}},
  interaction:{hover:true},
});
</script></body></html>"""


def _sample_verify_html():
    rows = [
        ("CONFIRMED","rapamycin","inhibits","mTOR",95,"Rapamycin inhibits mTOR kinase through FKBP12 binding"),
        ("CONFIRMED","mTOR","regulates","autophagy",91,"mTOR regulates autophagic flux in nutrient-deprived cells"),
        ("CONFIRMED","BRCA1","associates_with","breast cancer",88,"BRCA1 mutations strongly associated with breast cancer"),
        ("CONFIRMED","p53","activates","apoptosis",94,"p53 directly activates pro-apoptotic gene expression"),
        ("CONFIRMED","rapamycin","extends_lifespan","Mus musculus",89,"Rapamycin extended median lifespan by 25% in mice"),
        ("MISMATCH","FOXO3","extends_healthspan","Homo sapiens",72,"Text mentions association but not confirmed healthspan extension"),
    ]
    row_html = ""
    for status, s, r, o, conf, evidence in rows:
        color   = "#34d399" if status == "CONFIRMED" else "#f87171"
        icon    = "✓" if status == "CONFIRMED" else "✗"
        row_html += f"""<tr>
          <td style="color:{color};font-weight:700;text-align:center">{icon}</td>
          <td><span style="background:#1a2235;padding:2px 8px;border-radius:4px;font-family:monospace;font-size:11px">{s}</span></td>
          <td><span style="background:#2563eb18;color:#4f9cf9;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">{r}</span></td>
          <td><span style="background:#1a2235;padding:2px 8px;border-radius:4px;font-family:monospace;font-size:11px">{o}</span></td>
          <td style="color:#6b8cbe;font-size:11px">{conf}%</td>
          <td style="color:#6b8cbe;font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{evidence}</td>
        </tr>"""
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Verification Report</title>
<style>
body{{margin:0;padding:28px;background:#0a0e17;font-family:Inter,sans-serif;color:#e6edf3}}
h1{{font-size:22px;font-weight:800;margin-bottom:4px;background:linear-gradient(120deg,#f0f6ff,#6b8cbe);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.sub{{color:#6b8cbe;font-size:13px;margin-bottom:24px}}
.score{{font-size:52px;font-weight:900;font-family:monospace;color:#34d399;line-height:1;margin-bottom:4px}}
.score-sub{{color:#6b8cbe;font-size:13px;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{text-align:left;padding:7px 10px;color:#3d5a80;font-size:10px;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #1e2d45}}
td{{padding:8px 10px;border-bottom:1px solid #111827;vertical-align:middle}}
tr:hover td{{background:#111827}}
</style></head><body>
<h1>🚀 Knowledge Graph — Verification Report</h1>
<div class="sub">Each triple verified against its source paper. Mock test data.</div>
<div class="score">94%</div>
<div class="score-sub">5 of 6 relations confirmed against source text</div>
<table><thead><tr><th></th><th>Subject</th><th>Relation</th><th>Object</th><th>Conf</th><th>Evidence</th></tr></thead>
<tbody>{row_html}</tbody></table>
</body></html>"""


@router.post("/api/run/test")
async def start_test_run():
    """Emit fake pipeline events to verify the UI works end-to-end."""
    import time as _time

    run_id = str(uuid.uuid4())[:8]
    _queues[run_id] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _emit(event):
        asyncio.run_coroutine_threadsafe(_queues[run_id].put(event), loop)

    def _mock():
        def _stopped(): return _stop_flags.get(run_id, False)
        def log(layer, msg):
            if _stopped(): return
            _emit({"layer": layer, "status": "log", "message": msg, "data": {}})
            _time.sleep(0.08)

        _emit({"layer":1,"status":"running","message":"Loading sources…","data":{}})
        log(1, "Reading config/sources.yaml")
        log(1, "Found 7 registered sources: pubmed, pmc, geo, clinicaltrials, biorxiv, pdf, medrxiv")
        log(1, "Input: PMC_TEST → matched to source: pmc")
        log(1, "Paper URL: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC_TEST/")
        _time.sleep(0.2)
        _emit({"layer":1,"status":"done","message":"Source Registry complete","data":{"source_name":"pmc","doc_id":"PMC_TEST","all_sources":[{"name":"pmc","type":"api","format":"xml"},{"name":"pubmed","type":"api","format":"xml"},{"name":"pdf","type":"file","format":"pdf"}],"paper_url":"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC_TEST/"}})

        _emit({"layer":2,"status":"running","message":"Checking deduplication…","data":{}})
        log(2, "Querying data/triple_store_neo4j.db for PMC_TEST")
        log(2, "Result: 0 existing triples — paper not yet processed")
        _time.sleep(0.2)
        _emit({"layer":2,"status":"done","message":"New paper — not in KG","data":{"already_processed":False,"existing_triples":0,"doc_id":"PMC_TEST"}})

        _emit({"layer":3,"status":"running","message":"Fetching paper…","data":{}})
        log(3, "GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC_TEST")
        log(3, "200 OK — 48,231 bytes received (XML)")
        log(3, "Step 2: Detecting format — XML/PubMed Central")
        log(3, "Step 3: Cleaning text — removing citations, figure refs")
        log(3, "Step 4: Coreference resolution — 3 chains resolved")
        log(3, '  Chain 1: "it" → "rapamycin" (3 occurrences)')
        log(3, '  Chain 2: "the protein" → "mTOR" (2 occurrences)')
        log(3, "Step 5: Section labeling — abstract, intro, results, discussion")
        log(3, "Step 6: Chunking — 6 chunks (avg 420 words each)")
        log(3, "  Chunk 1 [abstract]:     312 words")
        log(3, "  Chunk 2 [introduction]: 501 words")
        log(3, "  Chunk 3 [results]:      438 words")
        log(3, "  Chunk 4 [results]:      389 words")
        log(3, "  Chunk 5 [discussion]:   412 words")
        log(3, "  Chunk 6 [discussion]:   298 words")
        _time.sleep(0.3)
        _emit({"layer":3,"status":"done","message":"Test Paper — Mock Pipeline — 6 chunks","data":{"doc_id":"PMC_TEST","title":"Test Paper — Mock Pipeline","chunks":6,"sections":["abstract","introduction","results","discussion"]}})

        _emit({"layer":4,"status":"running","message":"Tagging entities…","data":{}})
        log(4, "Loading scispaCy models: BC5CDR, JNLPBA, BioNLP13CG")
        log(4, "Running NER ensemble on 6 chunks…")
        log(4, "  Chunk 1: 8 entities — BRCA1 (GENE), p53 (PROTEIN), rapamycin (CHEMICAL)")
        log(4, "  Chunk 2: 11 entities — mTOR (GENE), autophagy (BIOLOGICAL_PROCESS)")
        log(4, "  Chunk 3: 9 entities — Alzheimer disease (DISEASE), tau (PROTEIN)")
        log(4, "  Chunk 4: 7 entities — Mus musculus (ORGANISM), mTOR (GENE)")
        log(4, "  Chunk 5: 5 entities — FOXO3 (GENE), lifespan (PHENOTYPE)")
        log(4, "  Chunk 6: 2 entities — rapamycin (CHEMICAL)")
        log(4, "Running NLI negation detector on 42 entities…")
        log(4, '  "failed to activate mTOR" → mTOR ABSENT (contradiction score: 0.87)')
        _time.sleep(0.4)
        _emit({"layer":4,"status":"done","message":"42 entities tagged","data":{"entity_count":42,"negated_count":3,"entity_types":["GENE","PROTEIN","DISEASE","CHEMICAL","ORGANISM"],"entities":[{"text":"BRCA1","label":"GENE","negated":False},{"text":"rapamycin","label":"CHEMICAL","negated":False},{"text":"mTOR","label":"GENE","negated":True}]}})

        _emit({"layer":5,"status":"running","message":"Loading schema…","data":{}})
        log(5, "Loading RelationType enum: 87 types in 22 categories")
        log(5, "Loading EntityType enum: 39 types")
        _time.sleep(0.15)
        _emit({"layer":5,"status":"done","message":"Schema ready","data":{"relation_types":87,"entity_types":39}})

        layers = [
            (6, "LLM Extraction", 2.0, {"viable":18,"chunks":6,"rejected":1}),
            (7, "Post-Extraction", 0.5, {"valid":16,"duplicates":1,"flagged":1,"contradictions":0,"relations":[
                {"subject":"rapamycin","relation":"inhibits","object":"mTOR","confidence":0.96,"verdict":"VALID"},
                {"subject":"mTOR","relation":"regulates","object":"autophagy","confidence":0.91,"verdict":"VALID"},
                {"subject":"BRCA1","relation":"associates_with","object":"breast cancer","confidence":0.88,"verdict":"VALID"},
                {"subject":"p53","relation":"activates","object":"apoptosis","confidence":0.94,"verdict":"VALID"},
                {"subject":"rapamycin","relation":"extends_lifespan","object":"Mus musculus","confidence":0.89,"verdict":"VALID"},
            ]}),
            (8, "Publish", 0.4, {"auto_insert":16,"human_review":2,"neo4j_nodes":24,"neo4j_edges":16,"metta_nodes":24,"metta_edges":16,"verified":15,"total":16,"ver_pct":94,"graph_html":"/api/test/graph","ver_html":"/api/test/verify","ver_results":[
                {"overall_status":"CONFIRMED","source_name":"rapamycin","label":"inhibits","target_name":"mTOR","supporting_text":"Rapamycin inhibits mTOR kinase activity through FKBP12 binding"},
                {"overall_status":"CONFIRMED","source_name":"BRCA1","label":"associates_with","target_name":"breast cancer","supporting_text":"BRCA1 mutations are strongly associated with breast cancer risk"},
                {"overall_status":"MISMATCH","source_name":"p53","label":"activates","target_name":"apoptosis","mismatch_reason":"Text mentions regulation but not direct activation"},
            ]}),
        ]
        for n, name, delay, data in layers:
            if _stopped(): break
            _emit({"layer":n,"status":"running","message":f"Processing {name}…","data":{}})
            if n == 6:
                for i in range(1, 7):
                    if _stopped(): break
                    _time.sleep(delay / 6)
                    _emit({"layer":6,"status":"progress","message":f"Chunk {i}/6","data":{"done":i,"total":6}})
            else:
                _time.sleep(delay)
            if not _stopped():
                _emit({"layer":n,"status":"done","message":f"{name} complete","data":data})
        if not _stopped():
            _time.sleep(0.3)
            _emit({"layer":0,"status":"complete","message":"Test pipeline finished"})

    threading.Thread(target=_mock, daemon=True).start()
    return JSONResponse({"run_id": run_id})


@router.post("/api/stop")
async def stop_run(run_id: str = Form(...)):
    _stop_flags[run_id] = True
    return JSONResponse({"ok": True})


@router.post("/api/run")
async def start_run(
    input_type:    str = Form(...),
    input_value:   str = Form(""),
    source_name:   str = Form(""),
    output_format: str = Form("both"),
    pdf_file: UploadFile = File(None),
):
    run_id = str(uuid.uuid4())[:8]
    _queues[run_id]     = asyncio.Queue()
    _stop_flags[run_id] = False

    if input_type == "pdf" and pdf_file:
        upload_dir = _ROOT / "data" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / pdf_file.filename
        with open(dest, "wb") as f:
            shutil.copyfileobj(pdf_file.file, f)
        input_value = str(dest)

    loop = asyncio.get_event_loop()

    def _thread_emit(event: dict):
        # Drop events after stop — don't fill the queue
        if _stop_flags.get(run_id):
            return
        try:
            asyncio.run_coroutine_threadsafe(_queues[run_id].put(event), loop)
        except KeyError:
            import logging as _log
            if event.get("status") == "error":
                _log.error(f"[run {run_id}] Pipeline error (client disconnected): {event.get('message', '')}")

    def _is_stopped():
        return _stop_flags.get(run_id, False)

    def _run():
        from api.pipeline_runner import run_pipeline
        run_pipeline(input_type, input_value, output_format,
                     _thread_emit, run_id, source_name=source_name,
                     is_stopped=_is_stopped)
        msg = "Pipeline stopped by user" if _stop_flags.get(run_id) else "Pipeline finished"
        asyncio.run_coroutine_threadsafe(
            _queues[run_id].put({"layer": 0, "status": "complete", "message": msg}),
            loop,
        )
        _stop_flags.pop(run_id, None)

    threading.Thread(target=_run, daemon=True).start()
    return JSONResponse({"run_id": run_id})


@router.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    await websocket.accept()
    _connections[run_id] = websocket
    if run_id not in _queues:
        _queues[run_id] = asyncio.Queue()
    try:
        while True:
            try:
                event = await asyncio.wait_for(_queues[run_id].get(), timeout=15)
                await websocket.send_text(json.dumps(event))
                if event.get("status") in ("complete", "fatal"):
                    _queues.pop(run_id, None)
                    break
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"layer": 0, "status": "ping"}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _connections.pop(run_id, None)
        # Queue intentionally NOT popped — pipeline may still be running; browser reconnect drains it.
