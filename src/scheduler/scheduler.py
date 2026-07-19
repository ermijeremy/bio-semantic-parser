import sqlite3
import hashlib
import logging
import os
import requests
from datetime import datetime, timezone, timedelta
from src.registry.registry import SourceRegistry

logger = logging.getLogger(__name__)

_DEFAULT_DB = os.getenv("PROCESSED_IDS_DB", "data/processed_ids.db")


class Scheduler:
    def __init__(self, registry: SourceRegistry, db_path: str = _DEFAULT_DB):
        self.registry = registry
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_ids (
                id           TEXT NOT NULL,
                format       TEXT NOT NULL DEFAULT 'both',
                source_name  TEXT,
                id_type      TEXT,
                processed_at TEXT,
                PRIMARY KEY (id, format)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS source_runs (
                source_name TEXT PRIMARY KEY,
                last_run TEXT
            )
        """)
        conn.commit()
        conn.close()

    # ── Scheduling ─────────────────────────────────────────
    def get_sources_to_check(self):
        return self.registry.get_all_sources()

    def run(self, fetcher) -> dict:
        results = {"processed": 0, "skipped": 0, "errors": 0}
        for source in self.registry.get_all_sources():
            if source.get("type") == "file":
                sub = self._scan_file_inbox(source, fetcher)
                for k in results:
                    results[k] += sub[k]
                continue

            search_query = source.get("search_query", "")
            if not search_query:
                logger.warning("No search_query set for source '%s' — skipping", source["name"])
                continue

            since = self.get_last_run(source["name"])
            logger.info("Checking %s for new papers since %s", source["name"], since)

            new_ids = self.get_new_ids(source, since)
            logger.info("%s: %d new IDs found", source["name"], len(new_ids))

            for doc_id in new_ids:
                id_type = "standard" if source.get("id_field") else "sha256"
                if not self.should_process(doc_id, source["name"], id_type):
                    results["skipped"] += 1
                    continue
                try:
                    url       = self._build_fetch_url(source, doc_id)
                    paper_url = self._build_paper_url(source, doc_id, url)
                    fetcher.fetch(url, source, doc_id, paper_url=paper_url)
                    results["processed"] += 1
                except Exception as e:
                    logger.error("Error processing %s from %s: %s", doc_id, source["name"], e)
                    results["errors"] += 1

            self.set_last_run(source["name"])

        return results

    def _scan_file_inbox(self, source: dict, fetcher) -> dict:
        results = {"processed": 0, "skipped": 0, "errors": 0}
        watch_dir = source.get("watch_dir", "")
        fmt = source.get("format", "")

        if not watch_dir or not os.path.isdir(watch_dir):
            logger.warning("Source '%s' watch_dir not found: '%s'", source["name"], watch_dir)
            return results

        for filename in os.listdir(watch_dir):
            if not filename.lower().endswith(f".{fmt}"):
                continue

            file_path = os.path.join(watch_dir, filename)
            with open(file_path, "rb") as f:
                doc_id = hashlib.sha256(f.read()).hexdigest()
            
            if not self.should_process(doc_id, source["name"], "sha256"):
                results["skipped"] += 1
                continue
            try:
                fetcher.fetch(file_path, source, doc_id)
                results["processed"] += 1
            except Exception as e:
                logger.error("Error processing file %s: %s", filename, e)
                results["errors"] += 1

        return results

    def get_last_run(self, source_name: str) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT last_run FROM source_runs WHERE source_name = ?", (source_name,)
        )
        result = cursor.fetchone()
        conn.close()
        if result:
            return result[0]
        return (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    
    # Saves current timestamp as the last run time for this source
    def set_last_run(self, source_name: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO source_runs (source_name, last_run) VALUES (?, ?)",
            (source_name, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        )
        conn.commit()
        conn.close()

    # ── New ID discovery per source type ───────────────────
    def get_new_ids(self, source: dict, since: str) -> list:
        name = source["name"]
        if name in ("pubmed", "pmc", "geo"):
            return self._query_ncbi(source, since)
        elif name == "biorxiv":
            return self._query_biorxiv(source, since)
        elif name == "clinicaltrials":
            return self._query_clinicaltrials(source, since)
        return []

    def _query_ncbi(self, source: dict, since: str) -> list:
        db_map = {"pubmed": "pubmed", "pmc": "pmc", "geo": "gds"}
        db = db_map[source["name"]]
        query = source["search_query"]
        today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        since_ncbi = since.replace("-", "/")
        api_key = os.getenv(source.get("api_key_env", ""), "")

        url = (
            f"{source['base_url']}esearch.fcgi"
            f"?db={db}&term={query}"
            f"&mindate={since_ncbi}&maxdate={today}"
            f"&retmode=json&retmax=100"
        )
        if api_key:
            url += f"&api_key={api_key}"

        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json().get("esearchresult", {}).get("idlist", [])

    def _query_biorxiv(self, source: dict, since: str) -> list:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = f"{source['base_url']}{since}/{today}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        collection = resp.json().get("collection", [])
        return [item["doi"] for item in collection if item.get("doi")]

    def _query_clinicaltrials(self, source: dict, since: str) -> list:
        base = source.get("base_url", "").rstrip("/")
        url = (
            f"{base}"
            f"?format=json"
            f"&filter.advanced=AREA[LastUpdatePostDate]RANGE[{since},MAX]"
            f"&pageSize=100"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        studies = resp.json().get("studies", [])
        return [
            s.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
            for s in studies
            if s.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
        ]

    # ── Fetch URL builder per source type ──────────────────
    def _build_fetch_url(self, source: dict, doc_id: str) -> str:
        name = source["name"]
        base = source.get("base_url", "")
        if name == "pubmed":
            return f"{base}efetch.fcgi?db=pubmed&id={doc_id}&retmode=xml"
        elif name == "pmc":
            return f"{base}efetch.fcgi?db=pmc&id={doc_id}&retmode=xml"
        elif name == "geo":
            return f"{base}efetch.fcgi?db=gds&id={doc_id}&retmode=xml"
        elif name == "biorxiv":
            return f"{base}{doc_id}"
        elif name == "clinicaltrials":
            return f"{base}{doc_id}"
        return ""

    def _build_paper_url(self, source: dict, doc_id: str, fetch_url: str) -> str:
        """Return the human-readable paper URL for provenance storage."""
        name = source["name"]
        if name == "pmc":
            return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{doc_id}/"
        elif name == "pubmed":
            return f"https://pubmed.ncbi.nlm.nih.gov/{doc_id}/"
        elif name == "biorxiv":
            return f"https://www.biorxiv.org/content/{doc_id}"
        elif name == "clinicaltrials":
            return f"https://clinicaltrials.gov/study/{doc_id}"
        elif name == "geo":
            return f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={doc_id}"
        # PDF — use the local path or original fetch_url as-is
        return fetch_url

    # ── ID management ──────────────────────────────────────
    def resolve_id(self, source: dict, content: str = None) -> tuple:
        id_field = source.get("id_field")
        if id_field and content:
            return content, "standard"
        raw = content or source["name"]
        return hashlib.sha256(raw.encode("utf-8")).hexdigest(), "sha256"

    # ── Early deduplication + crash safety ─────────────────
    def get_processed_by_source(self, source_name: str) -> list:
        """Return list of (id, processed_at) for all docs from a given source."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT id, processed_at FROM processed_ids WHERE source_name = ? ORDER BY processed_at DESC",
            (source_name,)
        )
        rows = cursor.fetchall()
        conn.close()
        return rows

    def processed_formats(self, doc_id: str) -> list:
        """
        Return list of (format, processed_at) for every COMPLETED format this doc
        was processed for.  Excludes 'pending' (recorded in Layer 2 before format
        is chosen — replaced by the real format when Layer 8 completes).
        """
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT format, processed_at FROM processed_ids "
            "WHERE id = ? AND format != 'pending' ORDER BY processed_at DESC",
            (doc_id,)
        ).fetchall()
        conn.close()
        return [(r[0], r[1]) for r in rows]

    def is_processed(self, doc_id: str, fmt: str = "") -> bool:
        """
        Return True if this doc was already processed.
        If fmt is given, check only that specific format (or 'both' which covers all).
        If fmt is empty, return True if processed for ANY format.
        """
        conn = sqlite3.connect(self.db_path)
        if fmt:
            cursor = conn.execute(
                "SELECT id FROM processed_ids "
                "WHERE id = ? AND (format = ? OR format = 'both')",
                (doc_id, fmt)
            )
        else:
            cursor = conn.execute(
                "SELECT id FROM processed_ids WHERE id = ?", (doc_id,)
            )
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def mark_processed(self, doc_id: str, source_name: str, id_type: str, fmt: str = "both"):
        """Record that doc_id was processed for the given format."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO processed_ids
               (id, format, source_name, id_type, processed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, fmt, source_name, id_type, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        conn.close()

    def should_process(self, doc_id: str, source_name: str, id_type: str, fmt: str = "both") -> bool:
        if self.is_processed(doc_id, fmt):
            logger.info("Skipping %s (format=%s) — already processed", doc_id, fmt)
            return False
        self.mark_processed(doc_id, source_name, id_type)
        return True
