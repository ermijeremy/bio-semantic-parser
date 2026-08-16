FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    COREF_MODEL=lingmess \
    COREF_DEVICE=cpu \
    COREF_RESOLVE_MODE=anaphora \
    COREF_PRELOAD=true \
    HF_HUB_DISABLE_XET=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Slow mirrors can drop the connection mid-download; retry instead of failing the build.
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install -r requirements.txt && \
    python -m spacy download en_core_web_sm

COPY app ./app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
  CMD curl -fsS http://localhost:5000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
