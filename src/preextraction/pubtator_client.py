"""
Layer 4 — PubTator3 Client

Fetches pre-annotated entities from the NIH/NLM PubTator3 API for a given
PubMed ID. Returns typed, normalized entities (NCBI Gene IDs, MeSH IDs, etc.)
that overlay and supplement the local scispaCy ensemble output.
"""
import logging
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)

_PUBTATOR3_URL = (
    "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
)

PUBTATOR_TYPE_MAP: dict[str, str] = {
    "Gene":     "GENE",
    "Disease":  "DISEASE",
    "Chemical": "SMALL_MOLECULE",
    "Species":  "ORGANISM",
    "Mutation": "GENOMIC_VARIANT",
    "CellLine": "CELL_LINE",
}


def fetch_pubtator_entities(pmid: str, timeout: int = 15) -> List[Dict]:
    """
    Fetch typed, normalized entities from PubTator3 for a PubMed article.
    Returns an empty list on network failure or missing PMID.
    """
    try:
        resp = requests.get(_PUBTATOR3_URL, params={"pmids": pmid}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        logger.warning("PubTator3 request timed out for PMID %s", pmid)
        return []
    except requests.exceptions.RequestException as e:
        logger.warning("PubTator3 request failed for PMID %s: %s", pmid, e)
        return []
    except ValueError as e:
        logger.warning("PubTator3 returned invalid JSON for PMID %s: %s", pmid, e)
        return []

    entities: List[Dict] = []
    seen: set = set()

    for article in data.get("PubTator3", []):
        for passage in article.get("passages", []):
            for ann in passage.get("annotations", []):
                text = ann.get("text", "").strip()
                if not text:
                    continue
                normalized = text.lower()
                if normalized in seen:
                    continue
                seen.add(normalized)

                infons     = ann.get("infons", {})
                label      = PUBTATOR_TYPE_MAP.get(infons.get("type", ""), "OTHER")
                identifier = infons.get("identifier", "") or infons.get("normalized_id", "")

                loc   = ann.get("locations", [{}])[0]
                start = loc.get("offset", -1)
                end   = (start + loc.get("length", 0)) if start >= 0 else -1
                entities.append({
                    "text":       text,
                    "normalized": normalized,
                    "label":      label,
                    "identifier": identifier,
                    "start":      start,
                    "end":        end,
                    "negated":    False,
                    "source":     "pubtator3",
                })

    return entities
