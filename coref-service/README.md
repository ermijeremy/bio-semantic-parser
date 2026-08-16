# Coreference Resolution Service

A small local service that performs coreference resolution. It replaces pronouns
and references with the entity they point to, so each sentence stands on its own.

```
in:  "Rapamycin was given daily. It reduced mTOR activity."
out: "Rapamycin was given daily. Rapamycin reduced mTOR activity."
```

## Model comparison: s2e-coref vs LingMess

Both are neural coreference models that use a Longformer encoder and are evaluated
on the OntoNotes benchmark.

| | s2e-coref | LingMess |
|---|---|---|
| Approach | Scores antecedents directly from token endpoints (low memory) | Separate expert scorers per mention-pair type |
| OntoNotes F1 | ~80.3 | ~81.4 |
| Packaging | Research repo, manual setup | `fastcoref` pip package |
| Speed option | None | Also ships FCoref, a faster distilled model |

**Chosen: LingMess (via `fastcoref`).** It scores higher, installs as a normal
package, and gives a faster fallback model (`fcoref`) through the same API.

Note: both models are trained on general English, not biomedical text. Tuning for
scientific text is a possible next step.

## Run

A prebuilt image is published, so there is no need to build from source:

```bash
cd coref-service
docker compose pull         # pulls ghcr.io/lnamty/coref-service:lingmess
docker compose up -d        # serves on http://localhost:5000
```

The first start downloads the model weights into the `coref-models` volume. Later
starts reuse them.

To build the image locally instead of pulling it:

```bash
docker compose build
docker compose up -d
```

## API

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/health` | | service and model status |
| POST | `/resolve` | `{"text": "..."}` | `{"resolved_text": "..."}` |
| POST | `/clusters` | `{"text": "..."}` | coreference clusters with offsets |

Example:

```bash
curl -X POST localhost:5000/resolve \
  -H 'Content-Type: application/json' \
  -d '{"text":"Rapamycin was given daily. It reduced mTOR activity."}'
```

## Configuration

Set these in `docker-compose.yml` or a `.env` file (see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `COREF_MODEL` | `lingmess` | `lingmess` (accurate) or `fcoref` (fast) |
| `COREF_DEVICE` | `cpu` | `cpu` or `cuda:0` |
| `COREF_RESOLVE_MODE` | `anaphora` | rewrite pronouns and `the X` references, or `pronouns_only` |
| `COREF_PRELOAD` | `true` | load the model at startup |
