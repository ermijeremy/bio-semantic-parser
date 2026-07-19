"""Bio Semantic Parser — FastAPI backend server (REST API + WebSocket)."""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from api.routes.query        import router as _query_router
from api.routes.sources      import router as _sources_router
from api.routes.pipeline     import router as _pipeline_router
from api.routes.human_review import router as _hr_router
from api.routes.kg           import router as _kg_router
from api.routes.misc         import router as _misc_router


@asynccontextmanager
async def _lifespan(application):
    import threading
    from api.pipeline_runner import warm_models
    threading.Thread(target=warm_models, daemon=True).start()
    yield


app = FastAPI(title="Bio Semantic Parser", lifespan=_lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(_query_router)
app.include_router(_sources_router)
app.include_router(_pipeline_router)
app.include_router(_hr_router)
app.include_router(_kg_router)
app.include_router(_misc_router)
