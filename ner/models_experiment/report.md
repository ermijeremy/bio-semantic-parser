Let me check the JSON for the deeper per-type detail and error logs before writing the report — the GLiNER-bi-large 0.0 score especially needs explaining.# NER Model Evaluation — Results Analysis & Strategy

Real, informative results. Let me walk through what happened, what's a bug vs. a genuine finding, and what to actually build.

---

## Critical Bug to Fix First

**GLiNER-BioMed-bi-large scored 0.0 — this is not a model failure, it's a library version mismatch.** Every single sentence (69/69) threw the same error:

```
BertModel.forward() got an unexpected keyword argument 'token_lengths'
```

This means the installed `gliner` pip version doesn't match what the bi-encoder checkpoint expects — the bi-encoder architecture passes an extra kwarg to the backbone that the current `transformers`/`gliner` version doesn't support. **Do not conclude the bi-encoder variant is bad.** Fix:

```python
!pip install -q -U gliner==0.2.13  # or check the model card for pinned version
```

Re-run before drawing any conclusion about GLiNER-bi-large's actual speed/accuracy tradeoff.

---

## What the Valid Results Actually Show

### GLiNER-BioMed-large is the clear winner — by a wide margin

| Metric | GLiNER-large | scispaCy baseline | Gap |
|---|---|---|---|
| Partial F1 | **0.875** | 0.688 | +0.187 |
| Tier-1 F1 | **0.936** | 0.809 | +0.127 |
| Schema coverage | **94.7%** | 28.9% | +65.8pp |
| Recall | **0.931** | 0.571 | +0.36 |

This confirms exactly what the 2025 benchmark literature predicted for your use case. It finds nearly everything (93% recall) across nearly the whole schema, at a completely acceptable 110ms/sentence.

### The exact-match F1 is misleadingly low for everyone — explain this correctly

Notice **every model** has terrible exact F1 (0.07–0.17) but strong partial F1 (0.26–0.88). This is not a detection failure — it's a **span boundary convention mismatch**. Your gold annotations include leading/trailing context words in spans (e.g. `"tumor suppressor protein"` as one span), while models often tag only the head noun (`"protein"`) or split multi-word spans differently. This is expected and normal in NER evaluation — **partial F1 is the metric that matters for your pipeline**, since downstream entity normalization (PubTator3) re-anchors spans to canonical IDs anyway and doesn't need pixel-perfect boundaries.

### The 3 specialist PubMedBERT models systematically fail — and it's a specific, diagnosable pattern

Look at the shared signature across all three:

| Model | Precision | Recall | F1 |
|---|---|---|---|
| BENT-PubMedBERT-Gene | 0.911 | 0.155 | 0.264 |
| BENT-PubMedBERT-Disease | 0.980 | 0.052 | 0.098 |
| PubMedBERT-ProteinStructure | 0.930 | 0.167 | 0.284 |

**Very high precision + very low recall, consistently, across all three.** This pattern means: when these models do tag something, they're almost always right — but they're missing the vast majority of true entities. This is a classic symptom of **narrow training distribution**. These checkpoints were fine-tuned on short, curated benchmark sentences (BC2GM, NCBI Disease corpus) that look nothing like your complex, multi-clause research sentences with nested appositives ("the PI3K-AKT-mTOR signalling pathway is hyperactivated in the majority of solid tumours"). The model recognizes entities it saw in training-style short declarative sentences but goes silent on the same entities embedded in longer, more complex prose — exactly the style real PMC full-text papers use.

**This is a genuinely useful finding for your Phase 3 report** — it means single-purpose fine-tuned checkpoints don't generalize to realistic scientific prose, which is a real, citable limitation of that model family for your specific pipeline.

### HunFlair2 is 10–100x slower than everything else, and underperformed

1188.6ms/sentence vs GLiNER's 109.8ms — over 10x slower. Its F1 of 0.398 is also well below the 59.97% cross-corpus benchmark figure reported in the literature. Two likely causes: (1) Flair's default embedding stack does multiple forward passes per sentence (character + word + contextual embeddings stacked), and (2) the cross-corpus benchmark tested on entire documents with rich context, while your test sentences are short standalone sentences — Flair's linear-chain CRF decoder benefits from longer context windows that single sentences don't provide.

At nearly 1.2 seconds per sentence, HunFlair2 is **not viable as a per-chunk pipeline component** at your expected document throughput — even as a Layer B specialist, it would create a severe bottleneck.

### scispaCy baseline has a label-mapping bug worth fixing regardless

`types_predicted` includes `CELL`, `ORGAN`, `ORGANISM_SUBSTANCE`, `SIMPLE_CHEMICAL` — these are raw BioNLP13CG labels that leaked through unmapped in your `SCISPACY_MAP` dictionary. This isn't affecting the F1 numbers much here, but in production this means some entities are getting non-schema type labels that will confuse the extraction LLM. Worth patching the map before this baseline is used anywhere.

---

## Revised Strategy

Given these results, the architecture simplifies significantly from the original 3-layer plan — the data doesn't support using the specialist models as designed.

### Layer A — GLiNER-BioMed-large (primary, does almost all the work)

Runs on every chunk. At 0.936 Tier-1 F1 and 94.7% schema coverage, this single model is carrying nearly the entire NER burden. 110ms/sentence is fast enough for your pipeline's throughput needs.

### Layer B — Narrow, targeted use only (not a broad specialist tier)

Given the specialist models' poor recall on realistic prose, **do not run them broadly as originally planned.** Instead:

- **Drop BENT-PubMedBERT-Gene, BENT-PubMedBERT-Disease, and PubMedBERT-ProteinStructure from the pipeline entirely** unless you specifically fine-tune them further on your own longer-sentence data. As tested, they add latency without adding recall.
- **Drop HunFlair2** from the real-time pipeline due to the 1.2s/sentence latency — it doesn't fit a per-chunk processing model at any reasonable document throughput. If its disease/chemical precision is ever needed, run it offline as a batch re-annotation pass on already-extracted low-confidence entities, not inline.

### Layer C — PubTator3 overlay (unchanged)

Still the right place to assign canonical IDs to GLiNER's confirmed spans.

### What replaces the abandoned Layer B

Since GLiNER-large already gets 0.936 Tier-1 F1 with 0.902 precision, the residual error is small and mostly boundary-related (visible from the exact-vs-partial F1 gap), not missing entities. Rather than adding more models, the highest-leverage next step is:

1. **Threshold tuning** — test GLiNER at thresholds 0.3, 0.4, 0.6 to see if recall improves further without precision collapsing
2. **Span boundary post-processing** — a light rule-based pass that extends/trims GLiNER spans to match your schema's span conventions (e.g. always include the head noun's modifiers)
3. **PubTator3 as the real "Layer B"** — since it does exact-match canonical ID lookup, it naturally filters out GLiNER's false positives (a false positive with no matching database entry gets flagged rather than propagating downstream)

---

## Immediate Action Items

1. **Fix GLiNER-bi-large's version bug and re-run** — you need this data point since bi-encoders may be significantly faster with only marginal accuracy loss, which matters at scale
2. **Fix the scispaCy label-mapping dictionary** — patch `CELL`, `ORGAN`, `ORGANISM_SUBSTANCE`, `SIMPLE_CHEMICAL` into your schema map (or explicitly drop them)
3. **Adopt GLiNER-BioMed-large as your sole primary NER model** — the data doesn't support the originally planned multi-specialist ensemble
4. **Document the specialist-model recall failure** in your Phase 3 report — it's a legitimate, useful negative result showing why single-purpose fine-tuned checkpoints don't transfer to realistic paper prose
5. **Do not deploy HunFlair2 inline** — its latency is incompatible with per-chunk processing at any realistic document throughput