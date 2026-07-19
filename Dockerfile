FROM python:3.12-slim

RUN apt-get update -o Acquire::Retries=3 && \
    apt-get install -y --no-install-recommends gcc g++ curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-docker.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-docker.txt

ARG SCISPACY_BASE=https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4
RUN pip install --quiet \
    "${SCISPACY_BASE}/en_core_sci_lg-0.5.4.tar.gz" \
    "${SCISPACY_BASE}/en_ner_bc5cdr_md-0.5.4.tar.gz" \
    "${SCISPACY_BASE}/en_ner_jnlpba_md-0.5.4.tar.gz" \
    "${SCISPACY_BASE}/en_ner_bionlp13cg_md-0.5.4.tar.gz" \
    "${SCISPACY_BASE}/en_ner_craft_md-0.5.4.tar.gz"

COPY . .

RUN mkdir -p data/checkpoints data/kg_output data/uploads data/pdf_inbox data/staging

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/api/status || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-keep-alive", "120"]
