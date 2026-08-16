"""HTTP API for the coreference service.

    GET  /health             -> service and model status
    POST /resolve  {"text"}  -> {"resolved_text": "..."}
    POST /clusters {"text"}  -> {"clusters": [[{start, end, text}, ...], ...]}
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.resolver import CorefResolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("coref-service")

MODEL = os.getenv("COREF_MODEL", "lingmess")
DEVICE = os.getenv("COREF_DEVICE", "cpu")
RESOLVE_MODE = os.getenv("COREF_RESOLVE_MODE", "anaphora")
PRELOAD = os.getenv("COREF_PRELOAD", "true").lower() == "true"

resolver = CorefResolver(model_name=MODEL, device=DEVICE, resolve_mode=RESOLVE_MODE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if PRELOAD:
        try:
            resolver.load()
        except Exception:
            logger.exception("Model preload failed; will retry on first request.")
    yield


app = FastAPI(title="Coreference Service", version="1.0.0", lifespan=lifespan)


class TextRequest(BaseModel):
    text: str


class ResolveResponse(BaseModel):
    resolved_text: str


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL,
        "device": DEVICE,
        "resolve_mode": RESOLVE_MODE,
        "model_loaded": resolver.ready,
    }


@app.post("/resolve", response_model=ResolveResponse)
def resolve(req: TextRequest):
    return ResolveResponse(resolved_text=resolver.resolve(req.text))


@app.post("/clusters")
def clusters(req: TextRequest):
    return {"clusters": resolver.clusters(req.text)}
