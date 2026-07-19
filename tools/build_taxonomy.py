#!/usr/bin/env python3
"""
tools/build_taxonomy.py
────────────────────────
Offline script — downloads ALL relation/predicate types from four source
schemas and compares every single one against our taxonomy.

Run from the project root:
    python tools/build_taxonomy.py
    python tools/build_taxonomy.py --output tools/coverage_report.json
    python tools/build_taxonomy.py --cache          # cache downloads

When to run:
  - Before adding new relation types to taxonomy.py
  - When source schemas release a new version
  - To verify taxonomy completeness

Sources
───────
  1. Hetionet v1.0        https://github.com/hetio/hetionet
                          describe/edges/metaedges.tsv
  2. Biolink Model        https://github.com/biolink/biolink-model
                          biolink-model.yaml  (~200+ predicates)
  3. OpenBioLink          https://github.com/OpenBioLink/OpenBioLink
                          src/openbiolink/edgeType.py  (full EdgeType enum)
  4. BioNLP Shared Tasks  Hardcoded from task-definition papers — no single
                          machine-readable source exists for BioNLP.
                          Tasks covered: GE 2009/2011, EPI 2011, ID 2011,
                          BB 2011/2013, GRN 2013

Output
──────
  Console: full per-schema table — COVERED ✓ / MISSING ✗ for every type
  JSON (--output): machine-readable report + suggested canonical names
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.schema.taxonomy import RelationType  # noqa: E402

# ── Synonym map (offline audit use only — not part of the runtime schema) ──────
SYNONYM_MAP = {
    # BioNLP event type aliases
    "Gene_expression":        RelationType.EXPRESSED_IN,
    "Transcription":          RelationType.TRANSCRIBES_TO,
    "Translation":            RelationType.TRANSLATES_TO,
    "Protein_catabolism":     RelationType.DEGRADES,
    "Protein_degradation":    RelationType.DEGRADES,
    "Phosphorylation":        RelationType.PHOSPHORYLATES,
    "Dephosphorylation":      RelationType.DEPHOSPHORYLATES,
    "Methylation":            RelationType.METHYLATES,
    "DNA_methylation":        RelationType.METHYLATES,
    "Acetylation":            RelationType.ACETYLATES,
    "Deacetylation":          RelationType.DEACETYLATES,
    "Ubiquitination":         RelationType.UBIQUITINATES,
    "Deubiquitination":       RelationType.DEUBIQUITINATES,
    "Sumoylation":            RelationType.SUMOYLATES,
    "Desumoylation":          RelationType.DESUMOYLATES,
    "Demethylation":          RelationType.DEMETHYLATES,
    "DNA_demethylation":      RelationType.DEMETHYLATES,
    "Hydroxylation":          RelationType.HYDROXYLATES,
    "Dehydroxylation":        RelationType.DEHYDROXYLATES,
    "Glycosylation":          RelationType.GLYCOSYLATES,
    "Deglycosylation":        RelationType.DEGLYCOSYLATES,
    "Glycan_synthesis":       RelationType.CONVERTS_TO,
    "Neddylation":            RelationType.NEDDYLATES,
    "Deneddylation":          RelationType.DENEDDYLATES,
    "Protein_processing":     RelationType.CLEAVES,
    "catalyzes":              RelationType.CATALYZES,
    "catalyses":              RelationType.CATALYZES,
    "coexpressed with":       RelationType.COEXPRESSED_WITH,
    "coexpressed_with":       RelationType.COEXPRESSED_WITH,
    "is missense variant of":    RelationType.IS_VARIANT_OF,
    "is synonymous variant of":  RelationType.IS_VARIANT_OF,
    "is nonsense variant of":    RelationType.IS_VARIANT_OF,
    "is frameshift variant of":  RelationType.IS_VARIANT_OF,
    "is splice site variant of": RelationType.IS_VARIANT_OF,
    "is nearby variant of":      RelationType.IS_VARIANT_OF,
    "is sequence variant of":    RelationType.IS_VARIANT_OF,
    "has sequence variant":      RelationType.IS_VARIANT_OF,
    "secretes":               RelationType.SECRETES,
    "releases":               RelationType.SECRETES,
    "Infection":              RelationType.INFECTS,
    "Immune_response":        RelationType.PROMOTES,
    "Transcription_activation": RelationType.ACTIVATES,
    "Transcription_repression": RelationType.INHIBITS,
    "Exhibits":               RelationType.HAS_PHENOTYPE,
    "Lives_in":               RelationType.LOCALIZES_TO,
    "Binding":                RelationType.BINDS_TO,
    "Localization":           RelationType.LOCALIZES_TO,
    "Transport":              RelationType.TRANSPORTS,
    "Conversion":             RelationType.CONVERTS_TO,
    "Regulation":             RelationType.REGULATES,
    "Positive_regulation":    RelationType.ACTIVATES,
    "Negative_regulation":    RelationType.INHIBITS,
    # Hetionet metaedge aliases
    "upregulates":            RelationType.UPREGULATES,
    "downregulates":          RelationType.DOWNREGULATES,
    "expresses":              RelationType.EXPRESSED_IN,
    "binds":                  RelationType.BINDS_TO,
    "palliates":              RelationType.PALLIATES,
    "resembles":              RelationType.RESEMBLES,
    "treats":                 RelationType.TREATS,
    "causes":                 RelationType.CAUSES,
    "associates":             RelationType.ASSOCIATES_WITH,
    "localizes":              RelationType.LOCALIZES_TO,
    "presents":               RelationType.HAS_SYMPTOM,
    "covaries":               RelationType.CORRELATES_WITH,
    "interacts":              RelationType.INTERACTS_WITH,
    "participates":           RelationType.PARTICIPATES_IN,
    "regulates":              RelationType.REGULATES,
    "includes":               RelationType.IS_MEMBER_OF,
}

CACHE_DIR = Path(__file__).parent / ".schema_cache"


# ── Shared fetch helper ───────────────────────────────────────────────────────

def _fetch(url: str, cache: bool = False, label: str = "") -> str:
    if cache:
        CACHE_DIR.mkdir(exist_ok=True)
        safe  = re.sub(r"[^\w.]", "_", url)[-80:]
        cfile = CACHE_DIR / safe
        if cfile.exists():
            print(f"  [cache] {label or url}")
            return cfile.read_text(encoding="utf-8")
    print(f"  [fetch] {label or url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    if cache:
        safe  = re.sub(r"[^\w.]", "_", url)[-80:]
        cfile = CACHE_DIR / safe
        cfile.write_text(resp.text, encoding="utf-8")
    return resp.text


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1 — Hetionet v1.0
# metaedges.tsv columns: metaedge | abbreviation | edges | ...
# "Anatomy - downregulates - Gene" → verb = "downregulates"
# ══════════════════════════════════════════════════════════════════════════════

HETIONET_URL = (
    "https://raw.githubusercontent.com/hetio/hetionet/main/"
    "describe/edges/metaedges.tsv"
)


def fetch_hetionet(cache: bool) -> list:
    raw = _fetch(HETIONET_URL, cache=cache, label="Hetionet metaedges.tsv")
    results = []
    for line in raw.strip().splitlines()[1:]:   # skip header
        cols = line.split("\t")
        if not cols:
            continue
        metaedge = cols[0].strip()              # "Anatomy - downregulates - Gene"
        abbrev   = cols[1].strip() if len(cols) > 1 else ""
        # Extract relation verb (middle word between " - " separators)
        parts = [p.strip() for p in metaedge.split(" - ")]
        if len(parts) == 3:
            verb = parts[1]
            results.append({
                "source_schema": "hetionet",
                "raw_name":      verb,
                "description":   f"{parts[0]} –[{verb}]→ {parts[2]}  ({abbrev})",
                "full_name":     metaedge,
            })
    return results


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2 — Biolink Model
# biolink-model.yaml → slots section → all predicates
# We keep slots that have a biological domain/range or inherit from "related to"
# ══════════════════════════════════════════════════════════════════════════════

BIOLINK_URL = (
    "https://raw.githubusercontent.com/biolink/biolink-model/master/biolink-model.yaml"
)

def fetch_biolink(cache: bool) -> list:
    """
    Fetches ALL slots from the biolink model YAML with no filtering.
    The report shows every slot — covered or not — so humans can decide
    which ones belong in the taxonomy.
    """
    raw  = _fetch(BIOLINK_URL, cache=cache, label="Biolink model YAML")
    data = yaml.safe_load(raw)
    slots = data.get("slots", {})

    results = []
    for slot_name, slot_body in slots.items():
        if not isinstance(slot_body, dict):
            continue
        results.append({
            "source_schema": "biolink",
            "raw_name":      slot_name,
            "description":   (slot_body.get("description") or "")[:100],
            "is_a":          (slot_body.get("is_a") or ""),
            "domain":        (slot_body.get("domain") or ""),
            "range":         (slot_body.get("range") or ""),
        })
    return results


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3 — OpenBioLink
# src/openbiolink/edgeType.py → EdgeType enum (all members)
# ══════════════════════════════════════════════════════════════════════════════

OPENBIOLINK_URL = (
    "https://raw.githubusercontent.com/OpenBioLink/OpenBioLink/master/"
    "src/openbiolink/edgeType.py"
)

_OBL_CANONICAL = {
    "IS_A":                       "",               # ontology hierarchy, not extraction
    "PART_OF":                    "part_of",
    "GENE_GENE":                  "interacts_with",
    "GENE_GO":                    "participates_in",
    "GENE_DIS":                   "associates_with",
    "GENE_DRUG":                  "is_target_of",
    "GENE_PHENOTYPE":             "has_phenotype",
    "GENE_PATHWAY":               "participates_in",
    "GENE_EXPRESSED_ANATOMY":     "expressed_in",
    "GENE_OVEREXPRESSED_ANATOMY": "upregulates",
    "GENE_UNDEREXPRESSED_ANATOMY":"downregulates",
    "DIS_DRUG":                   "treats",
    "DIS_PHENOTYPE":              "has_symptom",
    "DIS_DIS":                    "resembles",
    "DRUG_PHENOTYPE":             "causes",
    "DRUG_ACTIVATION_GENE":       "activates",
    "DRUG_BINDING_GENE":          "binds_to",
    "DRUG_CATALYSIS_GENE":        "regulates",
    "DRUG_EXPRESSION_GENE":       "regulates",
    "DRUG_INHIBITION_GENE":       "inhibits",
    "DRUG_PREDBIND_GENE":         "binds_to",
    "DRUG_REACTION_GENE":         "converts_to",
    "DRUG_BINDACT_GENE":          "activates",
    "DRUG_BINDINH_GENE":          "inhibits",
    "GENE_ACTIVATION_GENE":       "activates",
    "GENE_BINDING_GENE":          "binds_to",
    "GENE_CATALYSIS_GENE":        "regulates",
    "GENE_EXPRESSION_GENE":       "regulates",
    "GENE_INHIBITION_GENE":       "inhibits",
    "GENE_PTMOD_GENE":            "regulates",    # PTM type unspecified
    "GENE_REACTION_GENE":         "converts_to",
    "GENE_BINDACT_GENE":          "activates",
    "GENE_BINDINH_GENE":          "inhibits",
    "GENE_PREDBIND_GENE":         "binds_to",
    "ANATOMY_ANATOMY":            "part_of",
}

_OBL_DESCRIPTIONS = {
    "IS_A":                      "ontology is-a / subclass relation",
    "PART_OF":                   "ontology part-of / component relation",
    "GENE_GENE":                 "gene–gene interaction (StringDB, BioGRID)",
    "GENE_GO":                   "gene participates in GO term (BP/MF/CC)",
    "GENE_DIS":                  "gene–disease association (DisGeNET, OMIM, ClinVar)",
    "GENE_DRUG":                 "gene is pharmacological target of drug (DrugBank, ChEMBL)",
    "GENE_PHENOTYPE":            "gene–phenotype association (HPO, ClinVar)",
    "GENE_PATHWAY":              "gene participates in pathway (KEGG, Reactome)",
    "GENE_EXPRESSED_ANATOMY":    "gene expressed in anatomy (GTEx / HPA)",
    "DIS_DRUG":                  "disease–drug relationship (indication / contraindication)",
    "DIS_PHENOTYPE":             "disease presents with phenotype (HPO)",
    "DRUG_PHENOTYPE":            "drug causes phenotype / side effect (SIDER, OFFSIDES)",
    "GENE_OVEREXPRESSED_ANATOMY":"gene overexpressed in anatomy (Bgee)",
    "GENE_UNDEREXPRESSED_ANATOMY":"gene underexpressed in anatomy (Bgee)",
    "DRUG_ACTIVATION_GENE":      "drug activates gene product (STITCH/STRING activation)",
    "DRUG_BINDING_GENE":         "drug binds gene product (STITCH/STRING binding)",
    "DRUG_CATALYSIS_GENE":       "drug catalyses reaction involving gene product",
    "DRUG_EXPRESSION_GENE":      "drug modulates expression of gene",
    "DRUG_INHIBITION_GENE":      "drug inhibits gene product (STITCH/STRING inhibition)",
    "DRUG_PREDBIND_GENE":        "drug predicted to bind gene product",
    "DRUG_REACTION_GENE":        "drug involved in reaction with gene product",
    "DRUG_BINDACT_GENE":         "drug binds and activates gene product",
    "DRUG_BINDINH_GENE":         "drug binds and inhibits gene product",
    "GENE_ACTIVATION_GENE":      "gene activates another gene/gene product",
    "GENE_BINDING_GENE":         "gene/protein binds another gene/protein",
    "GENE_CATALYSIS_GENE":       "gene/enzyme catalyses reaction on gene product",
    "GENE_EXPRESSION_GENE":      "gene modulates expression of another gene",
    "GENE_INHIBITION_GENE":      "gene inhibits another gene/gene product",
    "GENE_PTMOD_GENE":           "gene modifies another gene via post-translational modification",
    "GENE_REACTION_GENE":        "gene involved in reaction with another gene",
    "GENE_BINDACT_GENE":         "gene binds and activates another gene",
    "GENE_BINDINH_GENE":         "gene binds and inhibits another gene",
    "GENE_PREDBIND_GENE":        "gene predicted to bind another gene",
    "ANATOMY_ANATOMY":           "anatomy is part of / subregion of another anatomy",
    "DIS_DIS":                   "disease–disease similarity",
}


def fetch_openbiolink(cache: bool) -> list:
    try:
        raw   = _fetch(OPENBIOLINK_URL, cache=cache, label="OpenBioLink edgeType.py")
        names = re.findall(r"^\s{4}([A-Z_]+)\s*=\s*\d", raw, re.MULTILINE)
        if names:
            return [{
                "source_schema": "openbiolink",
                "raw_name":      n,
                "description":   _OBL_DESCRIPTIONS.get(n, n.replace("_", " ").lower()),
            } for n in names]
    except Exception as exc:
        print(f"  [warn] OpenBioLink fetch failed ({exc}) — using fallback list")

    # Fallback: hardcoded from paper
    return [{"source_schema": "openbiolink", "raw_name": k, "description": v}
            for k, v in _OBL_DESCRIPTIONS.items()]


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 4 — BioNLP Shared Tasks (hardcoded — no machine-readable source)
# Covers: GE 2009/2011, EPI 2011, ID 2011, BB 2011/2013, GRN 2013
# ══════════════════════════════════════════════════════════════════════════════

_BIONLP_TYPES = [
    # ── GE 2009 / GE 2011 — Gene Expression task ──────────────────────────────
    ("Gene_expression",         "GE",  "gene/protein is expressed (baseline detection)"),
    ("Transcription",           "GE",  "gene is transcribed to RNA product"),
    ("Translation",             "GE",  "RNA is translated to protein product"),
    ("Protein_catabolism",      "GE",  "protein is catabolised or degraded"),
    ("Phosphorylation",         "GE",  "protein is phosphorylated"),
    ("Localization",            "GE",  "protein/molecule localises to a compartment"),
    ("Binding",                 "GE",  "protein-protein or protein-DNA binding"),
    ("Regulation",              "GE",  "regulation of entity (direction unspecified)"),
    ("Positive_regulation",     "GE",  "positive regulation / activation"),
    ("Negative_regulation",     "GE",  "negative regulation / inhibition"),
    ("Transport",               "GE",  "active transport of molecule between compartments"),
    ("Conversion",              "GE",  "metabolic conversion of substrate to product"),
    ("Cell_proliferation",      "GE",  "biological process — cell proliferation"),
    ("Cell_differentiation",    "GE",  "biological process — cell differentiation"),
    ("Development",             "GE",  "biological process — developmental event"),
    ("Remodeling",              "GE",  "tissue or matrix remodeling event"),
    # ── EPI 2011 — Epigenetics task ───────────────────────────────────────────
    ("Methylation",             "EPI", "addition of methyl group (by methyltransferase)"),
    ("DNA_methylation",         "EPI", "methylation of DNA CpG site"),
    ("DNA_demethylation",       "EPI", "removal of methyl group from DNA"),
    ("Acetylation",             "EPI", "addition of acetyl group (by acetyltransferase)"),
    ("Deacetylation",           "EPI", "removal of acetyl group (by sirtuin or HDAC)"),
    ("Ubiquitination",          "EPI", "addition of ubiquitin tag (by E3 ligase)"),
    ("Deubiquitination",        "EPI", "removal of ubiquitin tag (by DUB enzyme)"),
    ("Sumoylation",             "EPI", "addition of SUMO modifier"),
    ("Desumoylation",           "EPI", "removal of SUMO modifier"),
    ("Hydroxylation",           "EPI", "addition of hydroxyl group (by hydroxylase)"),
    ("Dehydroxylation",         "EPI", "removal of hydroxyl group"),
    ("Glycosylation",           "EPI", "addition of sugar / glycan moiety"),
    ("Deglycosylation",         "EPI", "removal of sugar / glycan moiety"),
    ("Glycan_synthesis",        "EPI", "de novo synthesis of a glycan chain"),
    ("Neddylation",             "EPI", "addition of NEDD8 modifier"),
    ("Deneddylation",           "EPI", "removal of NEDD8 modifier"),
    ("Dephosphorylation",       "EPI", "removal of phosphate group (by phosphatase)"),
    ("Protein_processing",      "EPI", "general post-translational processing or cleavage"),
    # ── ID 2011 — Infectious Diseases task ────────────────────────────────────
    ("Infection",               "ID",  "organism infects or colonises a host"),
    ("Immune_response",         "ID",  "host immune response to infection"),
    # ── BB 2011 / BB 2013 — Bacteria Biotopes task ────────────────────────────
    ("Lives_in",                "BB",  "bacterium lives in / inhabits host or environment"),
    ("Exhibits",                "BB",  "organism exhibits a biological property"),
    # ── GRN 2013 — Gene Regulation Network task ───────────────────────────────
    ("Transcription_activation","GRN", "gene activates transcription of target gene"),
    ("Transcription_repression","GRN", "gene represses transcription of target gene"),
]


def fetch_bionlp() -> list:
    seen: set = set()
    results = []
    for name, task, desc in _BIONLP_TYPES:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            results.append({
                "source_schema": f"bionlp_{task.lower()}",
                "raw_name":      name,
                "description":   desc,
            })
    return results


# ══════════════════════════════════════════════════════════════════════════════
# COVERAGE CHECK
# ══════════════════════════════════════════════════════════════════════════════

def _canonical_for(raw_name: str, source_schema: str = "") -> str:
    """Return canonical RelationType value if covered, else empty string."""
    if source_schema == "openbiolink":
        return _OBL_CANONICAL.get(raw_name, "")

    import re as _re
    normalised = _re.sub(r"[ \-]+", "_", raw_name.lower()).strip("_")

    for alias, rel in SYNONYM_MAP.items():
        alias_norm = _re.sub(r"[ \-]+", "_", alias.lower()).strip("_")
        if alias_norm == normalised:
            return rel.value
    for rel in RelationType:
        if rel.value == normalised or rel.name.lower() == normalised:
            return rel.value
    return ""


def check_coverage(all_types: list) -> list:
    for entry in all_types:
        canonical          = _canonical_for(entry["raw_name"], entry.get("source_schema", ""))
        entry["canonical"] = canonical
        entry["covered"]   = bool(canonical)
    return all_types


# ══════════════════════════════════════════════════════════════════════════════
# REPORT
# ══════════════════════════════════════════════════════════════════════════════

_SCHEMA_ORDER = [
    "hetionet",
    "bionlp_ge", "bionlp_epi", "bionlp_id", "bionlp_bb", "bionlp_grn",
    "openbiolink",
    "biolink",
]
_GREEN = "\033[32m✓\033[0m"
_RED   = "\033[31m✗\033[0m"


def print_report(all_types: list) -> None:
    by_schema: dict = {}
    for entry in all_types:
        by_schema.setdefault(entry["source_schema"], []).append(entry)

    total         = len(all_types)
    total_covered = sum(1 for e in all_types if e["covered"])

    print("\n" + "═" * 72)
    print("  TAXONOMY COVERAGE REPORT")
    print("  Our taxonomy vs. BioNLP + Hetionet + OpenBioLink + Biolink")
    print("═" * 72)

    for schema in _SCHEMA_ORDER + sorted(set(by_schema) - set(_SCHEMA_ORDER)):
        entries = by_schema.get(schema, [])
        if not entries:
            continue
        covered = sum(1 for e in entries if e["covered"])
        print(f"\n── {schema.upper()}  ({covered}/{len(entries)} covered) " + "─" * 30)
        for e in sorted(entries, key=lambda x: (not x["covered"], x["raw_name"])):
            mark      = _GREEN if e["covered"] else _RED
            canonical = f"  →  {e['canonical']}" if e.get("canonical") else ""
            desc      = f"  [{e['description'][:55]}]" if e.get("description") else ""
            print(f"  {mark}  {e['raw_name']:<42}{canonical}{desc}")

    print("\n" + "═" * 72)
    pct = (100 * total_covered // total) if total else 0
    print(f"  TOTAL: {total_covered}/{total} covered  ({pct}%)")

    missing = [e for e in all_types if not e["covered"]]
    if missing:
        seen_missing: set = set()
        unique_missing = []
        for e in missing:
            if e["raw_name"] not in seen_missing:
                seen_missing.add(e["raw_name"])
                unique_missing.append(e)

        print(f"\n  MISSING — {len(unique_missing)} unique types not yet in taxonomy")
        print("  ─" * 36)
        print("  Ready-to-paste additions for taxonomy.py RelationType enum:\n")
        for e in unique_missing:
            suggested = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", e["raw_name"]).upper()
            suggested = re.sub(r"[^A-Z_]", "_", suggested).strip("_")
            val       = suggested.lower()
            print(f"  # {e['source_schema']}: {e['raw_name']} — {e['description']}")
            print(f"  {suggested:<35} = \"{val}\"")
        print()
    else:
        print("\n  All schema types are covered. Taxonomy is complete.\n")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download all schema types and check taxonomy coverage."
    )
    parser.add_argument("--output", metavar="FILE",
                        help="Write full JSON report to FILE")
    parser.add_argument("--cache", action="store_true",
                        help="Cache downloaded files in tools/.schema_cache/")
    args = parser.parse_args()

    print("\nDownloading schemas…")
    print("─" * 72)

    all_types: list = []

    print("\n[1/4] Hetionet v1.0")
    all_types.extend(fetch_hetionet(cache=args.cache))

    print("\n[2/4] Biolink Model")
    all_types.extend(fetch_biolink(cache=args.cache))

    print("\n[3/4] OpenBioLink")
    all_types.extend(fetch_openbiolink(cache=args.cache))

    print("\n[4/4] BioNLP Shared Tasks (hardcoded from task papers)")
    all_types.extend(fetch_bionlp())

    print(f"\n  Total types collected: {len(all_types)}")

    all_types = check_coverage(all_types)
    print_report(all_types)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(all_types, indent=2, default=str), encoding="utf-8"
        )
        print(f"  JSON report written to: {out}")


if __name__ == "__main__":
    main()
