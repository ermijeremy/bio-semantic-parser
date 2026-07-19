"""Layer 7 step 1 — maps entity text to canonical biomedical identifiers via OLS4, NCBI, UniProt, RxNorm, and Wikidata."""
import re
import requests
from typing import Optional


_TIMEOUT  = 8
_NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_OLS_BASE  = "https://www.ebi.ac.uk/ols4/api"

# OLS4 in-process cache — avoids redundant API calls for repeated terms.
_ols4_cache: dict = {}


# ── Biolink → OLS4 ontology filter (gene/variant databases handled separately) ─
_TYPE_TO_ONTOLOGIES: dict = {
    "GENE":                        ["ensembl", "hgnc"],
    "PROTEIN":                     ["pr", "hgnc"],
    "TRANSCRIPT":                  ["so"],
    "EXON":                        ["so"],
    "NON_CODING_RNA":              ["so"],
    "GENOMIC_VARIANT":             ["so"],
    "SEQUENCE_VARIANT":            ["so"],
    "STRUCTURAL_VARIANT":          ["so"],
    "HAPLOTYPE":                   ["so"],
    "GENOTYPE":                    [],
    "REGULATORY_REGION":           ["so", "obi"],
    "ENHANCER":                    ["so"],
    "SUPER_ENHANCER":              ["so"],
    "PROMOTER":                    ["so"],
    "TRANSCRIPTION_FACTOR_BINDING_SITE": ["so"],
    "EPIGENOMIC_FEATURE":          ["so", "obi"],
    "MOTIF":                       ["so"],
    "TAD":                         ["so"],
    "SMALL_MOLECULE":              ["chebi", "mesh"],
    "DISEASE":                     ["mondo", "mesh", "doid"],
    "CANCER":                      ["mondo", "ncit", "mesh"],
    "PHENOTYPE":                   ["hp", "mp", "mesh"],
    "SYMPTOM":                     ["hp", "mesh"],
    "PATHWAY":                     ["pw", "go"],
    "REACTION":                    ["go"],
    "BIOLOGICAL_PROCESS":          ["go"],
    "MOLECULAR_FUNCTION":          ["go"],
    "CELLULAR_COMPONENT":          ["go"],
    "ANATOMY":                     ["uberon", "mesh"],
    "TISSUE":                      ["uberon", "bto", "mesh"],
    "CELL_TYPE":                   ["cl", "mesh"],
    "CELL_LINE":                   ["clo", "mesh"],
    "DEVELOPMENTAL_STAGE":         ["uberon"],
    "EXPERIMENTAL_FACTOR":         ["efo", "obi"],
    "THREE_D_GENOME_STRUCTURE":    ["so"],
    "MOLECULAR_INTERACTION":       ["mi"],
    "MACROMOLECULAR_COMPLEX":      ["go"],
    "ORGANISM":                    ["ncbitaxon"],
}

# Common organism names → NCBITaxon IDs (local fast lookup, no API needed)
_TAXON_LOCAL: dict = {
    "human": "9606",     "humans": "9606",    "homo sapiens": "9606",
    "mouse": "10090",    "mice": "10090",     "mus musculus": "10090",
    "rat": "10116",      "rats": "10116",     "rattus norvegicus": "10116",
    "fly": "7227",       "drosophila": "7227","drosophila melanogaster": "7227",
    "worm": "6239",      "c. elegans": "6239","caenorhabditis elegans": "6239",
    "yeast": "4932",     "saccharomyces cerevisiae": "4932",
    "zebrafish": "7955", "danio rerio": "7955",
    "dog": "9615",       "canis lupus familiaris": "9615",
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower().strip()).strip("_")


# ── Generic name pre-cleaning ────────────────────────────────────────────────

def _clean_name(text: str) -> str:
    """Strip PDF extraction artifacts (ligatures, soft hyphens, citations) before any lookup."""
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff") \
               .replace("ﬃ", "ffi").replace("ﬄ", "ffl").replace("ﬅ", "st")
    text = text.replace("­", "").replace("​", "").replace("﻿", "")
    # "pro- tein" → "protein"
    text = re.sub(r"-\s+", "", text)
    # "cholesterol biosynthesis.35" → "cholesterol biosynthesis"
    text = re.sub(r"\s*\.\d+(\s*,\s*\d+)*\s*$", "", text)
    # "NFY family [12]" → "NFY family"
    text = re.sub(r"\s*\[\d+\]\s*$", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # "human human APOE" → "human APOE"
    words = text.split()
    dedup = [words[0]] + [w for i, w in enumerate(words[1:], 1) if w.lower() != words[i-1].lower()]
    return " ".join(dedup)


def _extract_embedded_ids(text: str) -> list:
    """Return canonical IDs embedded in a name (rsID, Ensembl, UniProt, OBO) using format patterns only."""
    found = []
    # dbSNP rsID: exactly rs + 4-12 digits (NCBI dbSNP format)
    for m in re.finditer(r"\brs\d{4,12}\b", text, re.I):
        found.append((m.group().lower(), "dbsnp"))
    # Ensembl stable gene ID (ENSG + 11 digits)
    for m in re.finditer(r"\bENSG\d{11}\b", text):
        found.append((f"ENSEMBL:{m.group()}", "ensembl"))
    # UniProt accession (6 or 10 chars): covers P12345, Q9Y2T1, A0A024RBG1, etc.
    for m in re.finditer(r"\b(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]{5}|[A-NR-Z][0-9][A-Z0-9]{8}[0-9])\b", text):
        found.append((f"UniProtKB:{m.group()}", "uniprot"))
    # OBO-style prefixed ID already embedded: e.g. "gene GO:0006914 expression"
    for m in re.finditer(r"\b([A-Z]{2,10}:[A-Z0-9_]{3,15})\b", text):
        if _is_canonical_id(m.group()):
            found.append((m.group(), "embedded_obo"))
    return found


def _try_core_term(text: str, entity_type: str) -> Optional[str]:
    """Resolve composite names by trying progressively shorter prefixes via OLS4/Ensembl."""
    words = text.strip().split()
    if len(words) < 2:
        return None
    ontologies = _TYPE_TO_ONTOLOGIES.get(entity_type, [])
    for n_words in range(len(words) - 1, 0, -1):
        core = " ".join(words[:n_words]).strip()
        if len(core) < 2:
            break
        candidate = _ols4_search(core, ontologies) or _ols4_search(core, [])
        if candidate:
            return candidate
        if entity_type in ("GENE", "PROTEIN", "TRANSCRIPT", "NON_CODING_RNA", ""):
            eid = _ensembl_search(core)
            if eid:
                return eid
    return None


def _is_canonical_id(s: str) -> bool:
    """True if s looks like a real canonical ID (has a DB prefix or is an rsID)."""
    if not s:
        return False
    if ":" in s:               # MESH:D..., GO:..., CHEBI:..., NCBITaxon:...
        return True
    if re.match(r"^rs\d+$", s, re.I):   # dbSNP rsID
        return True
    if re.match(r"^ENSG\d+|^ENST\d+|^P\d{5}$", s):  # Ensembl / UniProt
        return True
    return False


# ── OLS4: universal ontology search ─────────────────────────────────────────

def _ols4_search(text: str, ontologies: list, timeout: int = _TIMEOUT) -> Optional[str]:
    """Search EBI OLS4, optionally scoped to specific ontologies; returns best-match ID (e.g. MESH:D031845)."""
    cache_key = (text.lower().strip(), tuple(sorted(ontologies)))
    if cache_key in _ols4_cache:
        return _ols4_cache[cache_key]
    result = _ols4_search_uncached(text, ontologies, timeout)
    _ols4_cache[cache_key] = result
    return result


def _ols4_search_uncached(text: str, ontologies: list, timeout: int = _TIMEOUT) -> Optional[str]:
    """Actual OLS4 HTTP call — called only on cache miss."""
    try:
        params: dict = {
            "q":     text,
            "rows":  1,
            "exact": "false",
            "fieldList": "id,obo_id,label,ontology_prefix",
        }
        if ontologies:
            params["ontology"] = ",".join(ontologies)

        r = requests.get(f"{_OLS_BASE}/search", params=params,
                         headers={"Accept": "application/json"}, timeout=timeout)
        docs = r.json().get("response", {}).get("docs", [])
        if docs:
            doc    = docs[0]
            obo_id = doc.get("obo_id") or doc.get("id", "")
            # Normalise to standard prefix:ID format
            if obo_id and "_" in obo_id:
                # OLS returns GO_0006914 → normalise to GO:0006914
                obo_id = obo_id.replace("_", ":", 1)
            if obo_id and ":" in obo_id:
                return obo_id
    except Exception:
        pass
    return None


# ── NCBI eSearch: genes, variants, taxonomy ──────────────────────────────────

def _ensembl_search(text: str, species: str = "human",
                    timeout: int = _TIMEOUT) -> Optional[str]:
    """Ensembl REST API — canonical gene IDs (ENSG format) per BioCypher alignment."""
    try:
        r = requests.get(
            f"https://rest.ensembl.org/xrefs/symbol/{species}/{text}",
            params={"content-type": "application/json", "object_type": "gene"},
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        data = r.json()
        if isinstance(data, list) and data:
            eid = data[0].get("id", "")
            if eid.startswith("ENSG"):
                return f"ENSEMBL:{eid}"
    except Exception:
        pass
    return None


def _ncbi_search(text: str, db: str, prefix: str,
                 extra_term: str = "", timeout: int = _TIMEOUT) -> Optional[str]:
    """Generic NCBI eSearch for any database."""
    try:
        term = f"{text}[All Fields]"
        if extra_term:
            term += f" AND {extra_term}"
        r = requests.get(f"{_NCBI_BASE}/esearch.fcgi",
                         params={"db": db, "term": term, "retmax": 1, "retmode": "json"},
                         timeout=timeout)
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if ids:
            return f"{prefix}{ids[0]}"
    except Exception:
        pass
    return None


def _pubchem_search(text: str, timeout: int = _TIMEOUT) -> Optional[str]:
    """PubChem REST API for small molecules not in ChEBI."""
    try:
        r = requests.get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{text}/cids/JSON",
            timeout=timeout)
        cids = r.json().get("IdentifierList", {}).get("CID", [])
        if cids:
            return f"PUBCHEM:{cids[0]}"
    except Exception:
        pass
    return None


def _uniprot_search(text: str, timeout: int = _TIMEOUT) -> Optional[str]:
    """UniProt REST API — canonical protein accessions (P12345 format)."""
    try:
        r = requests.get(
            "https://rest.uniprot.org/uniprotkb/search",
            params={"query": text, "format": "json", "size": 1,
                    "fields": "accession,protein_name,gene_names"},
            headers={"Accept": "application/json"}, timeout=timeout,
        )
        results = r.json().get("results", [])
        if results:
            acc = results[0].get("primaryAccession", "")
            if acc:
                return f"UniProtKB:{acc}"
    except Exception:
        pass
    return None


def _rxnorm_search(text: str, timeout: int = _TIMEOUT) -> Optional[str]:
    """RxNorm API (US NLM) — resolves both generic names and brand names to RxCUI."""
    try:
        r = requests.get(
            "https://rxnav.nlm.nih.gov/REST/rxcui.json",
            params={"name": text, "search": 1}, timeout=timeout,
        )
        rxcui = r.json().get("idGroup", {}).get("rxnormId", [])
        if rxcui:
            return f"RxNorm:{rxcui[0]}"
        # Approximate match for misspellings / synonyms not in exact index
        r2 = requests.get(
            "https://rxnav.nlm.nih.gov/REST/approximateTerm.json",
            params={"term": text, "maxEntries": 1}, timeout=timeout,
        )
        candidates = r2.json().get("approximateGroup", {}).get("candidate", [])
        if candidates:
            rxcui2 = candidates[0].get("rxcui", "")
            if rxcui2:
                return f"RxNorm:{rxcui2}"
    except Exception:
        pass
    return None


def _hmdb_search(_text: str, _timeout: int = _TIMEOUT) -> Optional[str]:
    """
    HMDB — Human Metabolome Database.
    NOTE: hmdb.ca uses Cloudflare which blocks programmatic access.
    We use PubChem as the metabolite resolver instead — it covers the same
    space with open API access. This function is kept as a stub in case
    HMDB provides a proper API in the future.
    PubChem is called directly in Priority 7 for SMALL_MOLECULE types.
    """
    return None


def _wikidata_search(text: str, entity_type: str, timeout: int = _TIMEOUT) -> Optional[str]:
    """Wikidata entity search — broad fallback; returns canonical DB ID when a type hint is available, else QID."""
    _WD_TYPE_HINTS = {
        "GENE":          "P351",    # NCBI Gene ID
        "PROTEIN":       "P352",    # UniProt ID
        "DISEASE":       "P699",    # Disease Ontology ID
        "SMALL_MOLECULE":"P662",    # PubChem CID
        "PATHWAY":       "P2410",   # Reactome ID
        "ORGANISM":      "P685",    # NCBI Taxonomy ID
    }
    prop = _WD_TYPE_HINTS.get(entity_type, "")
    try:
        r = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={"action": "wbsearchentities", "search": text,
                    "language": "en", "format": "json", "limit": 1},
            headers={"User-Agent": "bio-semantic-parser/1.0 (research@rejuve.bio)"},
            timeout=timeout,
        )
        items = r.json().get("search", [])
        if items:
            qid = items[0].get("id", "")
            if qid:
                if prop:
                    r2 = requests.get(
                        f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json",
                        timeout=timeout,
                    )
                    claims = r2.json().get("entities", {}).get(qid, {}).get("claims", {})
                    vals = claims.get(prop, [])
                    if vals:
                        ext_id = vals[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
                        if ext_id:
                            _WD_PREFIX = {
                                "GENE":          "NCBI_GENE:",
                                "PROTEIN":       "UniProtKB:",
                                "DISEASE":       "DOID:",
                                "SMALL_MOLECULE":"PUBCHEM:",
                                "PATHWAY":       "REACTOME:",
                                "ORGANISM":      "NCBITaxon:",
                            }
                            pfx = _WD_PREFIX.get(entity_type, "")
                            return f"{pfx}{ext_id}" if pfx else ext_id
                return f"WD:{qid}"
    except Exception:
        pass
    return None


# ── Main normalization function ───────────────────────────────────────────────

def normalize_entity(
    text: str,
    entity_type: str,
    existing_id: Optional[str] = None,
) -> dict:
    """Normalize one entity to a canonical ID; returns {canonical_id, id_source, needs_review}."""
    if not text or not text.strip():
        return {"canonical_id": "NEEDS_REVIEW", "id_source": "review", "needs_review": True}

    # ── Priority 1: Accept PubTator3 ID if it's already canonical ───────────
    if existing_id and _is_canonical_id(existing_id):
        return {"canonical_id": existing_id, "id_source": "pubtator3", "needs_review": False}

    # ── Pre-clean: strip PDF artifacts before any lookup ─────────────────────
    text = _clean_name(text)
    if not text:
        return {"canonical_id": "NEEDS_REVIEW", "id_source": "review", "needs_review": True}

    # ── Pattern extraction: canonical IDs embedded in composite names ─────────
    embedded = _extract_embedded_ids(text)
    if embedded:
        canon_id, source = embedded[0]
        return {"canonical_id": canon_id, "id_source": source, "needs_review": False}

    # ── Infer entity type from name structure when LLM type is unreliable ─────
    if re.match(r"^rs\d{4,}$", text.strip(), re.I):
        # rsIDs are always dbSNP regardless of declared entity_type
        return {"canonical_id": text.strip().lower(), "id_source": "dbsnp", "needs_review": False}
    if re.match(r"^ENSG\d{10,}$", text.strip()):
        return {"canonical_id": f"ENSEMBL:{text.strip()}", "id_source": "ensembl", "needs_review": False}

    # ── Priority 2: Fast local lookup for common organisms ───────────────────
    if entity_type == "ORGANISM":
        lower = text.lower().strip()
        if lower in _TAXON_LOCAL:
            return {"canonical_id": f"NCBITaxon:{_TAXON_LOCAL[lower]}",
                    "id_source": "ncbi_taxon", "needs_review": False}

    # ── Priority 3: Ensembl — checked before OLS4 so genes get ENSG not HGNC ───
    if entity_type in ("GENE", "TRANSCRIPT", "EXON", "NON_CODING_RNA"):
        eid = _ensembl_search(text)
        if eid:
            return {"canonical_id": eid, "id_source": "ensembl", "needs_review": False}

    # ── Priority 4: OLS4 universal search (primary resolver) ─────────────────
    ontologies = _TYPE_TO_ONTOLOGIES.get(entity_type, [])
    ols_id = _ols4_search(text, ontologies)
    if ols_id:
        return {"canonical_id": ols_id, "id_source": "ols4", "needs_review": False}

    # ── Priority 5: UniProt — OLS4 misses many protein isoforms and synonyms ───
    if entity_type == "PROTEIN":
        uid = _uniprot_search(text)
        if uid:
            return {"canonical_id": uid, "id_source": "uniprot", "needs_review": False}

    # ── Priority 6: RxNorm — covers brand names OLS4/ChEBI miss (e.g. Rapamune) ─
    if entity_type == "SMALL_MOLECULE":
        rxid = _rxnorm_search(text)
        if rxid:
            return {"canonical_id": rxid, "id_source": "rxnorm", "needs_review": False}

    # ── Priority 7: HMDB — metabolite synonyms OLS4 ChEBI search misses ────────
    if entity_type == "SMALL_MOLECULE":
        hid = _hmdb_search(text)
        if hid:
            return {"canonical_id": hid, "id_source": "hmdb", "needs_review": False}

    # ── Priority 8: NCBI eSearch fallback per entity type ────────────────────
    if entity_type in ("GENE", "PROTEIN", "TRANSCRIPT", "EXON", "NON_CODING_RNA"):
        gid = _ncbi_search(text, "gene", "NCBI_GENE:", "Homo sapiens[Organism]")
        if gid:
            return {"canonical_id": gid, "id_source": "ncbi_gene", "needs_review": False}

    if entity_type in ("GENOMIC_VARIANT", "SEQUENCE_VARIANT", "HAPLOTYPE"):
        snp = _ncbi_search(text, "snp", "rs")
        if snp:
            return {"canonical_id": snp, "id_source": "dbsnp", "needs_review": False}

    if entity_type == "ORGANISM":
        tid = _ncbi_search(text, "taxonomy", "NCBITaxon:")
        if tid:
            return {"canonical_id": tid, "id_source": "ncbi_taxon", "needs_review": False}

    if entity_type == "SMALL_MOLECULE":
        pub = _pubchem_search(text)
        if pub:
            return {"canonical_id": pub, "id_source": "pubchem", "needs_review": False}

    # ── Priority 9: OLS4 without ontology filter — always, not just typed ────
    ols_broad = _ols4_search(text, [])
    if ols_broad:
        return {"canonical_id": ols_broad, "id_source": "ols4_broad", "needs_review": False}

    # ── Priority 10: Composite decomposition — "PICALM loci" → PICALM ──────────
    core_id = _try_core_term(text, entity_type)
    if core_id:
        return {"canonical_id": core_id, "id_source": "ols4_core", "needs_review": False}

    # ── Priority 11: Wikidata — broad fallback covering anything not in above ──
    wd = _wikidata_search(text, entity_type)
    if wd:
        return {"canonical_id": wd, "id_source": "wikidata", "needs_review": False}

    # ── Priority 12: TEXT:slug — consistent fallback, never bare text ─────────
    slug = _slug(text)
    if slug:
        return {"canonical_id": f"TEXT:{slug}", "id_source": "fuzzy", "needs_review": True}

    return {"canonical_id": "NEEDS_REVIEW", "id_source": "review", "needs_review": True}


def normalize_batch(records: list, chunk: dict) -> list:
    """Normalize a list of records against a single chunk."""
    return [normalize_record(r, chunk) for r in records]


def normalize_record(record: dict, annotated_chunk: dict) -> dict:
    """Normalize subject and object entities in one extraction record; adds *_id and *_id_source fields."""
    subject_name = record.get("subject_name", "")
    subject_type = record.get("subject_type", "OTHER")
    object_name  = record.get("object_name",  "")
    object_type  = record.get("object_type",  "OTHER")

    layer4_map: dict = {
        e["text"].lower(): e.get("identifier") or e.get("normalized", "")
        for e in annotated_chunk.get("entities", [])
        if e.get("identifier") or e.get("normalized")
    }

    subj_norm = normalize_entity(
        subject_name, subject_type,
        existing_id=layer4_map.get(subject_name.lower(), ""),
    )
    obj_norm = normalize_entity(
        object_name, object_type,
        existing_id=layer4_map.get(object_name.lower(), ""),
    )

    review_reason = ""
    if subj_norm["needs_review"]:
        review_reason += f"subject '{subject_name}' not normalized; "
    if obj_norm["needs_review"]:
        review_reason += f"object '{object_name}' not normalized"

    return {
        **record,
        "subject_id":         subj_norm["canonical_id"],
        "subject_id_source":  subj_norm["id_source"],
        "subject_needs_review": subj_norm["needs_review"],
        "object_id":          obj_norm["canonical_id"],
        "object_id_source":   obj_norm["id_source"],
        "object_needs_review": obj_norm["needs_review"],
        "review_reason":      review_reason.strip("; "),
    }
