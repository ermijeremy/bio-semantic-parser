# BioNER Model Comparison

Isolated implementations of biomedical NER models behind a common interface,
plus a shared gold corpus, an evaluation harness, and a Flask dashboard to
compare their results and performance.

This generalises the exploration in
[`src/models_experiment/ner_comparison.ipynb`](../src/models_experiment/ner_comparison.ipynb)
into a reusable package: one file per model, lazy loading, and a UI instead of a
notebook.

## Layout

```
ner/
├── base.py            # Entity dataclass + BaseNERModel interface
├── schema.py          # 39-type BioCypher schema, NER-detectability tiers, GLiNER labels/maps
├── corpus.py          # 69-sentence gold corpus (char-offset spans)
├── evaluation.py      # exact/partial span metrics + per-model corpus scoring
├── app.py             # Flask dashboard (Extract + Benchmark)
├── templates/index.html
├── static/{style.css, app.js}
└── models/            # one isolated file per model
    ├── __init__.py    # registry (lightweight metadata; no heavy imports)
    ├── _hf_pipeline.py            # shared HF token-classification helper
    ├── gliner_biomed_large.py
    ├── gliner_biomed_base.py
    ├── gliner_biomed_bi_large.py
    ├── scispacy_ensemble.py
    ├── biomedical_ner_all.py      # d4data/biomedical-ner-all   [researched]
    ├── stanza_bionlp13cg.py       # Stanford Stanza             [researched]
    ├── hunflair2.py
    ├── bent_gene.py
    ├── bent_disease.py
    ├── pubmedbert_protein_structure.py
    ├── biobert_diseases.py        # alvaroalon2                 [researched]
    ├── biobert_chemical.py        # alvaroalon2                 [researched]
    └── biobert_genetic.py         # alvaroalon2                 [researched]
```

## Models (13)

| Key | Model | Family | Notes |
|---|---|---|---|
| `gliner_biomed_large` | Ihor/gliner-biomed-large-v1.0 | GLiNER zero-shot | Broadest coverage, best F1 in notebook |
| `gliner_biomed_base` | Ihor/gliner-biomed-base-v1.0 | GLiNER zero-shot | Smaller/faster — **researched addition** |
| `gliner_biomed_bi_large` | Ihor/gliner-biomed-bi-large-v1.0 | GLiNER zero-shot | Bi-encoder; pin `gliner` if `token_lengths` errors |
| `scispacy_ensemble` | BC5CDR + JNLPBA + BioNLP13CG | scispaCy | Fast CPU baseline (current pipeline default) |
| `biomedical_ner_all` | d4data/biomedical-ner-all | Transformer (fixed) | 41 clinical types (MACCROBAT) — **researched** |
| `stanza_bionlp13cg` | stanza en/bionlp13cg | Stanza | CharLM+BiLSTM+CRF, non-transformer — **researched** |
| `hunflair2` | hunflair/hunflair2-ner | Flair | High precision, ~1.2 s/sentence (offline) |
| `bent_gene` | pruas/BENT-PubMedBERT-NER-Gene | Transformer (fixed) | Gene/protein specialist |
| `bent_disease` | pruas/BENT-PubMedBERT-NER-Disease | Transformer (fixed) | Disease specialist |
| `pubmedbert_protein_structure` | PDBEurope/…ProteinStructure-NER-v3.1 | Transformer (fixed) | Residue/site/domain/complex |
| `biobert_diseases` | alvaroalon2/biobert_diseases_ner | BioBERT (fixed) | Disease baseline — **researched** |
| `biobert_chemical` | alvaroalon2/biobert_chemical_ner | BioBERT (fixed) | Chemical baseline — **researched** |
| `biobert_genetic` | alvaroalon2/biobert_genetic_ner | BioBERT (fixed) | Gene/protein baseline — **researched** |

The **researched additions** (six models beyond the notebook's seven) come from a
scan of the current biomedical-NER landscape:
[GLiNER-BioMed](https://huggingface.co/Ihor/gliner-biomed-base-v1.0),
[d4data/biomedical-ner-all](https://huggingface.co/d4data/biomedical-ner-all),
[Stanza biomedical models](https://stanfordnlp.github.io/stanza/available_biomed_models.html),
and the [alvaroalon2 BioBERT NER](https://huggingface.co/alvaroalon2/biobert_diseases_ner) family.

## Install

Core UI only (registry + dashboard, no model backends):

```bash
pip install flask
```

Add backends for the models you actually want to run (see
[`requirements.txt`](requirements.txt) for the grouping). Everything is lazy —
nothing downloads until you select a model in the UI.

```bash
pip install -r ner/requirements.txt   # everything (large)
```

## Run the dashboard

From the **repo root**:

```bash
python -m ner.app
# → http://127.0.0.1:5001   (override with NER_UI_PORT)
```

- **Extract** tab — type/paste a sentence, pick models, see highlighted entities
  side by side with per-model latency (first run of a model is a *cold start*
  and includes download + load).
- **Benchmark** tab — score selected models on the 69-sentence gold corpus;
  sortable table (partial/exact/tier-1 F1, precision, recall, coverage, latency,
  GPU) plus F1 and latency bar charts. Results are cached per model; tick
  *ignore cache* to re-run.

## Colab notebooks (one per model)

[`ner/notebooks/`](notebooks/) has a self-contained Google Colab notebook per
model (`01_…` … `13_…`). Each notebook checks the GPU, installs only that
model's backend, clones this repo to reuse the shared harness, runs a sanity
check, benchmarks the model on the gold corpus, and plots per-type F1 + a
summary, saving `ner_report_<key>.{json,png}`.

Usage on Colab: open a notebook → **Runtime → Change runtime type → T4 GPU** →
**Run all**. The clone step needs the `ner/` folder pushed to the `ner_models`
branch (or upload it to `/content` manually).

Regenerate all notebooks after changing the registry or install map:

```bash
python -m ner.notebooks._generate
```

## Adding a model

Drop a new file in `ner/models/` exposing a `get_model()` that returns a
`BaseNERModel` subclass implementing `load()` and `_predict(text) -> list[Entity]`,
then add one entry to `REGISTRY` in `ner/models/__init__.py`. Map the model's
native labels onto the schema types in `ner/schema.py` where possible; unmapped
labels fall through to `OTHER`.

## Metrics

- **Partial F1** (overlap + same type) is the headline metric — downstream
  entity normalisation (PubTator3) re-anchors spans to canonical IDs, so exact
  boundary agreement matters less than getting the right type on an overlapping
  span. Exact F1 is reported too but runs low for every model due to span
  boundary conventions.
- **Tiers** (`schema.py`): T1 types have strong surface signal and NER should
  detect them; T2 are context-dependent; T3 (TAD, MOTIF, structural variants…)
  are rarely named in prose and are expected to be resolved by database lookup,
  not NER.
