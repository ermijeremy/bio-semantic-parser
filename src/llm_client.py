"""Shared LLM client — OpenAI-compatible, wall-clock timeout, global concurrency cap."""
import concurrent.futures
import json
import os
import re
import threading

import httpx
from openai import OpenAI


# ── Config ───────────────────────────────────────────────────────────────────
BASE_URL     = os.getenv("LLM_BASE_URL",    "http://localhost:11434/v1")
API_KEY      = os.getenv("LLM_API_KEY",     "ollama")
MODEL        = os.getenv("LLM_MODEL",       "gemma2:27b")
TEMPERATURE  = float(os.getenv("LLM_TEMPERATURE",  "0.0"))
MAX_TOKENS   = int(os.getenv("LLM_OUTPUT_TOKENS",  "2048"))
WALL_TIMEOUT = int(os.getenv("LLM_WALL_TIMEOUT",   "300"))

_GLOBAL_CONCURRENCY = int(os.getenv("LLM_GLOBAL_CONCURRENCY", "4"))
_global_sem         = threading.Semaphore(_GLOBAL_CONCURRENCY)


def make_client() -> OpenAI:
    # Fresh client per call — keepalive disabled to prevent silent stale-connection hangs.
    return OpenAI(
        api_key     = API_KEY,
        base_url    = BASE_URL,
        http_client = httpx.Client(
            limits  = httpx.Limits(
                max_keepalive_connections = 0,
                max_connections           = 1,
            ),
            timeout = httpx.Timeout(600.0, connect=10.0),
        ),
    )


_RETRY_WAIT       = int(os.getenv("LLM_RETRY_WAIT",       "60"))
_RETRY_BUDGET     = int(os.getenv("LLM_RETRY_BUDGET",     "5"))
# Stagger completions to prevent burst arrivals that trigger vLLM scheduler freeze.
_COMPLETION_DELAY = float(os.getenv("LLM_COMPLETION_DELAY", "2"))

# Global rate limiter: minimum gap between HTTP submissions — prevents burst re-submissions that cause Running:0 Waiting:N freeze.
_submit_lock      = threading.Lock()
_last_submit_at   = [0.0]
_SUBMIT_INTERVAL  = float(os.getenv("LLM_SUBMIT_INTERVAL", "2.0"))


def call_llm(
    messages:     list,
    model:        str  = "",
    temperature:  float = None,
    max_tokens:   int   = None,
    wall_timeout: int   = None,
    json_mode:    bool  = True,
) -> str:
    import time as _time

    _model        = model        or MODEL
    _temperature  = temperature  if temperature  is not None else TEMPERATURE
    _max_tokens   = max_tokens   if max_tokens   is not None else MAX_TOKENS
    _wall_timeout = wall_timeout if wall_timeout is not None else WALL_TIMEOUT

    kwargs: dict = dict(
        model       = _model,
        messages    = messages,
        temperature = _temperature,
        max_tokens  = _max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(_RETRY_BUDGET + 1):
        client = make_client()

        def _call(kw=kwargs, _client=client):
            kw = {**kw, "messages": messages}
            return _client.chat.completions.create(**kw)

        # Single throttle point for all users/layers.
        _global_sem.acquire()
        # Enforce minimum gap between submissions to prevent burst that triggers the vLLM scheduler freeze.
        with _submit_lock:
            import time as _t
            gap = _SUBMIT_INTERVAL - (_t.time() - _last_submit_at[0])
            if gap > 0:
                _t.sleep(gap)
            _last_submit_at[0] = _t.time()
        pool   = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_call)
        try:
            response = future.result(timeout=_wall_timeout)
            if _COMPLETION_DELAY > 0:
                _time.sleep(_COMPLETION_DELAY)
            return response.choices[0].message.content or ""
        except concurrent.futures.TimeoutError:
            # Best-effort cancellation; the underlying request may still be in flight.
            future.cancel()
            if attempt < _RETRY_BUDGET:
                print(
                    f"[llm_client] vLLM timeout (attempt {attempt+1}/{_RETRY_BUDGET+1}). "
                    f"Waiting {_RETRY_WAIT}s then retrying — restart vLLM if stuck.",
                    flush=True,
                )
                _time.sleep(_RETRY_WAIT)
                continue
            raise TimeoutError(
                f"LLM did not respond within {_wall_timeout}s after {_RETRY_BUDGET+1} attempts"
            )
        finally:
            try:
                client.close()
            except Exception:
                pass
            pool.shutdown(wait=False, cancel_futures=True)
            _global_sem.release()


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$",        "", raw)
    return json.loads(raw.strip())


def check_server() -> None:
    server_root = BASE_URL.rstrip("/").removesuffix("v1").rstrip("/")
    try:
        httpx.get(f"{server_root}/health", timeout=8.0)
        return
    except Exception:
        pass
    try:
        httpx.get(f"{server_root}/v1/models",
                  headers={"Authorization": f"Bearer {API_KEY}"}, timeout=8.0)
    except Exception as e:
        raise ConnectionError(f"LLM server unreachable at {BASE_URL} — {e}")
