"""Generate one self-cloning Google Colab notebook per registered model.

Each notebook: checks the GPU, installs that model's backend, clones this repo
to reuse the shared harness (schema/corpus/evaluation), runs a sanity check,
benchmarks the model on the 69-sentence gold corpus, and plots the results.

Regenerate after changing the registry or install map:

    python -m ner.notebooks._generate
"""
from __future__ import annotations

import json
import os

from ner.models import REGISTRY

REPO_URL = "https://github.com/ermijeremy/bio-semantic-parser"
BRANCH = "ner_models"
HERE = os.path.dirname(__file__)

# Per-model install commands (shell lines, run with '!'). Fall back to extras.
SCISPACY_PKGS = [
    "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz",
    "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_jnlpba_md-0.5.4.tar.gz",
    "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bionlp13cg_md-0.5.4.tar.gz",
]

INSTALL = {
    "gliner_biomed_large": ["pip install -q -U gliner"],
    "gliner_biomed_base": ["pip install -q -U gliner"],
    "gliner_biomed_bi_large": [
        "pip install -q -U gliner  # bi-encoder needs a recent gliner; older builds throw a 'token_lengths' error",
    ],
    "scispacy_ensemble": ["pip install -q scispacy"] + [f"pip install -q {u}" for u in SCISPACY_PKGS],
    "biomedical_ner_all": ["pip install -q -U transformers"],
    "stanza_bionlp13cg": ["pip install -q stanza"],
    "hunflair2": ["pip install -q flair scispacy"],
    "bent_gene": ["pip install -q -U transformers"],
    "bent_disease": ["pip install -q -U transformers"],
    "pubmedbert_protein_structure": ["pip install -q -U transformers"],
    "biobert_diseases": ["pip install -q -U transformers"],
    "biobert_chemical": ["pip install -q -U transformers"],
    "biobert_genetic": ["pip install -q -U transformers"],
}

# A relevant sanity-check sentence per model family.
SANITY = {
    "gliner_biomed_large": "miR-21 upregulation in the substantia nigra of Parkinson disease patients activates the PI3K-AKT pathway.",
    "gliner_biomed_base": "miR-21 upregulation in the substantia nigra of Parkinson disease patients activates the PI3K-AKT pathway.",
    "gliner_biomed_bi_large": "miR-21 upregulation in the substantia nigra of Parkinson disease patients activates the PI3K-AKT pathway.",
    "scispacy_ensemble": "BRCA1 and TP53 mutations drive cancer progression in HeLa cells.",
    "biomedical_ner_all": "The patient presented with type 2 diabetes, hyperglycaemia, and was treated with metformin.",
    "stanza_bionlp13cg": "EGFR amplification drives oncogenic signalling in glioblastoma cells of the human brain.",
    "hunflair2": "Rapamycin inhibits mTOR and extends lifespan in Caenorhabditis elegans.",
    "bent_gene": "BRCA1, TP53 and the p53 tumour suppressor protein regulate the cell cycle.",
    "bent_disease": "Alzheimer disease and type 2 diabetes are common age-related disorders.",
    "pubmedbert_protein_structure": "The p53 protein is phosphorylated at Ser15 within its DNA-binding domain.",
    "biobert_diseases": "Alzheimer disease and type 2 diabetes are common age-related disorders.",
    "biobert_chemical": "Metformin and rapamycin were administered alongside dasatinib and quercetin.",
    "biobert_genetic": "BRCA1, TP53 and EGFR are frequently mutated genes in human cancers.",
}


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _lines(text)}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": _lines(text)}


def _lines(text: str) -> list:
    """nbformat wants a list of lines, each ending in \\n except the last."""
    lines = text.strip("\n").split("\n")
    return [ln + "\n" for ln in lines[:-1]] + [lines[-1]]


def build_notebook(key: str, meta: dict) -> dict:
    name = meta["name"]
    model_id = meta["model_id"]
    desc = meta["description"]
    family = meta["family"]
    homepage = f"https://huggingface.co/{model_id}" if "/" in model_id and not model_id.startswith("stanza") else meta.get("homepage", "")
    install_lines = INSTALL.get(key, [f"pip install -q {e}" for e in meta["extras"]])
    sanity_text = SANITY.get(key, "BRCA1 and BRCA2 mutations confer a high risk of breast and ovarian cancer.")
    gpu_note = ("This model benefits from a GPU. " if meta["prefers_gpu"]
                else "This model runs fine on CPU, but a GPU speeds it up. ")

    cells = []

    cells.append(md(f"""
# {name} — BioNER on Google Colab

**Model:** `{model_id}`  ·  **Family:** {family}

{desc}

{gpu_note}Set **Runtime → Change runtime type → T4 GPU** before running.

This notebook reuses the shared harness (39-type schema, 69-sentence gold corpus,
evaluation metrics) from the `ner/` package in the repo. It:
1. checks the GPU, 2. installs this model's backend, 3. clones the repo,
4. runs a sanity check, 5. benchmarks on the gold corpus, 6. plots results.
"""))

    cells.append(md("## 1 · Environment / GPU check"))
    cells.append(code("""
import torch
print("PyTorch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory/1e9:.1f} GB")
else:
    print("No GPU — Runtime -> Change runtime type -> T4 GPU")
"""))

    cells.append(md("## 2 · Install this model's backend"))
    cells.append(code("\n".join("!" + ln for ln in install_lines)))

    cells.append(md(f"""## 3 · Get the shared harness

Clones this repo (branch `{BRANCH}`) so we can import `ner.models`,
`ner.corpus`, and `ner.evaluation`. The `ner/` folder must be committed to the
branch. If you haven't pushed it yet, run `git add ner && git commit && git push`
locally first, or upload the `ner/` folder to `/content` manually."""))
    cells.append(code(f"""
import os, sys, subprocess

REPO_URL = "{REPO_URL}"
BRANCH   = "{BRANCH}"
CLONE_DIR = "/content/bio-semantic-parser"

if not os.path.isdir(CLONE_DIR):
    subprocess.run(
        ["git", "clone", "--branch", BRANCH, "--depth", "1", REPO_URL, CLONE_DIR],
        check=True,
    )

if CLONE_DIR not in sys.path:
    sys.path.insert(0, CLONE_DIR)

assert os.path.isdir(os.path.join(CLONE_DIR, "ner")), (
    "ner/ package not found in the clone — commit & push the ner/ folder to the "
    f"'{{BRANCH}}' branch, or upload it to {{CLONE_DIR}} manually."
)
print("Harness ready:", CLONE_DIR)
"""))

    cells.append(md("## 4 · Load the model & sanity check"))
    cells.append(code(f"""
from ner.models import load_model
from ner.schema import tier_of

KEY = "{key}"
model = load_model(KEY)          # lazy: downloads + loads on first predict
print("Loaded:", model.name, "|", model.model_id)

text = {sanity_text!r}
print("\\nSanity check:", text)
for e in sorted(model.predict(text), key=lambda x: x.start):
    print(f"  [{{e.label}} / {{tier_of(e.label)}}] {{e.text!r}}  ({{e.score:.2f}})")
"""))

    cells.append(md("""## 5 · Try your own text

Edit the `text` string below and re-run this cell to test the model on your own
input — highlighted spans are printed as `[label / tier] "text" (score)`."""))
    cells.append(code("""
# ✏️  Replace this with your own biomedical text, then re-run the cell.
text = \"\"\"BRCA1 and BRCA2 mutations confer a high lifetime risk of breast and ovarian cancer.\"\"\"

from ner.schema import tier_of
ents = sorted(model.predict(text), key=lambda x: x.start)
print(f"{len(ents)} entities found in {len(text)} chars\\n")
for e in ents:
    print(f"  [{e.label} / {tier_of(e.label)}] {e.text!r}  ({e.score:.2f})")
"""))

    cells.append(md("""## 6 · Benchmark on the gold corpus

Exact & partial (overlap + same-type) precision/recall/F1 over all 69 sentences,
plus tier-1 F1, schema coverage, latency, and GPU peak memory."""))
    cells.append(code("""
from ner.corpus import CORPUS, corpus_stats
from ner.evaluation import evaluate_model

print(corpus_stats()["n_sentences"], "sentences,",
      corpus_stats()["total_gold_entities"], "gold entities\\n")

report = evaluate_model(model.name, model.predict, CORPUS)

o, t1 = report["overall"], report["tier1_only"]
print(f"Overall   partial F1: {o['partial_f1']}   exact F1: {o['exact_f1']}")
print(f"          precision:  {o['partial_precision']}   recall: {o['partial_recall']}")
print(f"Tier-1    partial F1: {t1['partial_f1']}")
print(f"Coverage: {report['type_coverage_pct']}% of schema types")
print(f"Latency:  avg {report['avg_latency_ms']} ms   p95 {report['p95_latency_ms']} ms")
print(f"GPU peak: {report['gpu_peak_mb']} MB")
if report["errors"]:
    print(f"\\n{len(report['errors'])} sentence error(s); first:", report["errors"][0])
"""))

    cells.append(md("## 7 · Per-type F1 & summary plot"))
    cells.append(code("""
import matplotlib.pyplot as plt

per_type = {t: m["partial_f1"] for t, m in report["per_type"].items()}
per_type = dict(sorted(per_type.items(), key=lambda kv: kv[1], reverse=True))

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, max(4, len(per_type) * 0.28)),
                               gridspec_kw={"width_ratios": [2, 1]})

ax1.barh(list(per_type.keys())[::-1], list(per_type.values())[::-1], color="#3B9ED8")
ax1.set_xlim(0, 1); ax1.set_xlabel("partial F1")
ax1.set_title(f"{model.name} — per-type partial F1")
ax1.grid(axis="x", alpha=0.3)

summary = {
    "Partial F1": report["overall"]["partial_f1"],
    "Tier-1 F1": report["tier1_only"]["partial_f1"],
    "Precision": report["overall"]["partial_precision"],
    "Recall": report["overall"]["partial_recall"],
    "Coverage": report["type_coverage_pct"] / 100,
}
ax2.bar(range(len(summary)), list(summary.values()),
        color=["#185FA5", "#3B9ED8", "#639922", "#EF9F27", "#8B2FC9"])
ax2.set_xticks(range(len(summary))); ax2.set_xticklabels(list(summary.keys()), rotation=35, ha="right")
ax2.set_ylim(0, 1); ax2.set_title("Summary"); ax2.grid(axis="y", alpha=0.3)
for i, v in enumerate(summary.values()):
    ax2.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=9)

plt.tight_layout()
plt.savefig(f"ner_report_{KEY}.png", dpi=140, bbox_inches="tight")
plt.show()
"""))

    cells.append(md("## 8 · Save the JSON report"))
    cells.append(code("""
import json

with open(f"ner_report_{KEY}.json", "w") as f:
    json.dump(report, f, indent=2, default=str)
print("Saved:", f"ner_report_{KEY}.json", "and", f"ner_report_{KEY}.png")
"""))

    return {
        "cells": cells,
        "metadata": {
            "colab": {"provenance": [], "toc_visible": True},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
            "accelerator": "GPU",
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def main() -> None:
    os.makedirs(HERE, exist_ok=True)
    written = []
    for i, (key, meta) in enumerate(REGISTRY.items(), 1):
        nb = build_notebook(key, meta)
        path = os.path.join(HERE, f"{i:02d}_{key}.ipynb")
        with open(path, "w") as f:
            json.dump(nb, f, indent=1)
        written.append(os.path.basename(path))
    print(f"Wrote {len(written)} notebooks to {HERE}:")
    for w in written:
        print("  -", w)


if __name__ == "__main__":
    main()
