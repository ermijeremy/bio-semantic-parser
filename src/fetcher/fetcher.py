import os
import time
import tempfile
import requests
from dotenv import load_dotenv
from src.fetcher.format_detector import FormatDetector
from src.fetcher.handlers import JSONHandler, XMLHandler, HTMLHandler, PDFHandler, TextHandler
from src.fetcher.cleaner import TextCleaner
from src.fetcher.coref_client import CorefClient
from src.fetcher.section_splitter import SectionSplitter
from src.fetcher.chunker import Chunker
from src.fetcher.metadata_attacher import MetadataAttacher

load_dotenv()


class Fetcher:

    def __init__(self, coref_url: str):
        self.format_detector = FormatDetector()
        self.cleaner = TextCleaner()
        self.coref_client = CorefClient(coref_url)
        self.section_splitter = SectionSplitter()
        self.chunker = Chunker()
        self.metadata_attacher = MetadataAttacher()
        self.timeout = int(os.getenv("REQUEST_TIMEOUT", "30"))

    def fetch(self, url: str, source: dict, document_id: str,
              verbose: bool = False, paper_url: str = "",
              log_cb=None) -> list:

        def log(msg):
            if log_cb:
                log_cb(msg)
            elif verbose:
                print(msg)

        # handle local file path (PDF or TXT fallback from recovery)
        if not url.startswith("http"):
            if not paper_url:
                paper_url = url   # local path is the "source" for PDFs
            log("  Step 1 — Reading local file...")
            raw_text = PDFHandler().extract(url)
            log(f"           ✓ Extracted {len(raw_text):,} chars from file")
            return self._run_steps(raw_text, None, source, document_id, url, log,
                                   paper_url=paper_url or url)

        # If no human-readable paper_url provided, construct one from source+doc_id
        if not paper_url:
            paper_url = _build_readable_url(source, document_id, url)

        log(f"  Step 1 — Fetching: {url}")
        self._rate_limit(source)
        response = requests.get(self._apply_api_key(url, source), timeout=self.timeout)
        content_type = response.headers.get("Content-Type", "")

        # ── Blocked PDF recovery ──────────────────────────────────────────────
        # When a PDF URL returns 403/blocked (e.g. medRxiv Cloudflare),
        # attempt recovery before failing:
        #  1. Check pdf_inbox for an already-downloaded copy
        #  2. Try harder download (browser headers + curl)
        #  3. Fall back to medRxiv/bioRxiv API abstract text
        if response.status_code in (403, 401, 429) and _is_pdf_url(url):
            log(f"           ✗ {response.status_code} — PDF access blocked  ({url})")
            recovered = _recover_blocked_pdf(url, document_id, log)
            if recovered:
                log(f"           ✓ Found in pdf_inbox — using: {recovered}")
                raw_text = PDFHandler().extract(recovered)
                return self._run_steps(raw_text, None, source, document_id,
                                       recovered, log, paper_url=paper_url or url)
            raise RuntimeError(
                f"Unable to download PDF (HTTP {response.status_code}) — "
                f"the server requires authentication or blocks automated access.\n"
                f"\n"
                f"Please download the PDF manually:\n"
                f"  1. Open in your browser: {url}\n"
                f"  2. Save the file to:     data/pdf_inbox/\n"
                f"  3. Re-run the pipeline  — it will use the saved file automatically."
            )

        log(f"           ✓ {response.status_code} OK  |  {content_type}  |  {len(response.content):,} bytes")

        chunks = self._run_steps(None, response, source, document_id, url, log,
                                paper_url=paper_url or url)

        # Auto-fallback: if PubMed returned abstract-only, try PMC full text
        if source.get("name") == "pubmed":
            sections = {c.get("section", "") for c in chunks}
            if sections <= {"abstract", "unknown", ""}:
                pmc_id = _lookup_pmc_id(document_id, source.get("api_key_env", ""))
                if pmc_id:
                    log(f"  ↳ PubMed abstract-only — fetching full text from PMC ({pmc_id})…")
                    try:
                        pmc_source = dict(source, name="pmc")
                        pmc_url = (
                            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                            f"?db=pmc&id={pmc_id}&rettype=full&retmode=xml"
                        )
                        pmc_paper_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/"
                        pmc_response = requests.get(
                            self._apply_api_key(pmc_url, pmc_source), timeout=self.timeout
                        )
                        if pmc_response.status_code == 200:
                            pmc_chunks = self._run_steps(
                                None, pmc_response, pmc_source, pmc_id, pmc_url, log,
                                paper_url=pmc_paper_url,
                            )
                            if len(pmc_chunks) > len(chunks):
                                log(f"           ✓ PMC full text: {len(pmc_chunks)} chunk(s) — using instead of abstract")
                                return pmc_chunks
                    except Exception as e:
                        log(f"           ✗ PMC fallback failed: {e}")

        return chunks

    def _run_steps(self, raw_text, response, source, document_id, url, log,
                   paper_url: str = ""):
        # Step 2 — detect format and extract text
        log("  Step 2 — Detecting format & extracting text...")
        if raw_text is not None:
            text = raw_text
            log(f"           ✓ Local file — {len(text):,} chars")
        else:
            content_type = response.headers.get("Content-Type", "")
            format_type = self.format_detector.detect(content_type)
            text = self._extract_text(format_type, response, source)
            log(f"           ✓ Format: {format_type.upper()}  |  Extracted: {len(text):,} chars")

        # Step 3 — noise removal
        log("  Step 3 — Cleaning noise...")
        before_len = len(text)
        text = self.cleaner.clean(text)
        log(f"           ✓ {before_len:,} → {len(text):,} chars  ({before_len - len(text):,} removed)")

        # Step 4 — coreference resolution
        log("  Step 4 — Resolving coreferences...")
        coref_url = self.coref_client.base_url
        if not self.coref_client.health_check():
            raise RuntimeError(
                f"Coreference service is offline or unreachable at '{coref_url}'. "
                "Set COREF_SERVICE_URL in your .env and ensure the service is running."
            )
        log(f"           Service : ONLINE  ({coref_url})")
        text_before = text
        text = self.coref_client.resolve(text)
        rewrites = _find_coref_rewrites(text_before, text)
        if rewrites:
            log(f"           Rewrites: {len(rewrites)} sentence(s) changed")
            # Emit all rewrites — no truncation
            # Use COREF_REWRITE marker so the web UI can apply diff coloring
            for i, (before, after) in enumerate(rewrites, 1):
                log(f"__COREF__{i}/{len(rewrites)}__{before}__||__{after}")
        else:
            log(f"           ✓ No pronouns resolved (text may already be unambiguous)")

        # Step 5 — section splitting
        log("  Step 5 — Splitting into sections...")
        sections = self.section_splitter.split(text)
        section_names = [s["section"] for s in sections]
        log(f"           ✓ {len(sections)} section(s): {section_names}")

        # Step 6 — chunking
        log("  Step 6 — Chunking sections...")
        chunks = self.chunker.chunk_document(sections)
        log(f"           ✓ {len(chunks)} chunk(s) produced")

        # Step 7 — metadata attachment
        log("  Step 7 — Attaching metadata...")
        chunks = self.metadata_attacher.attach(chunks, document_id, source["name"], url,
                                               paper_url=paper_url)
        log(f"           ✓ Metadata attached: doc_id, source_name, url, paper_url, section, chunk_index")

        return chunks

    def _apply_api_key(self, url: str, source: dict) -> str:
        key_env = source.get("api_key_env")
        if not key_env:
            return url
        api_key = os.getenv(key_env, "")
        if not api_key:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}api_key={api_key}"

    def _rate_limit(self, source: dict):
        rate = source.get("rate_limit")
        if rate:
            time.sleep(1 / rate)

    def _extract_text(self, format_type: str, response, source: dict) -> str:
        if format_type == "json":
            return JSONHandler().extract(
                response.text, source.get("text_field")
            )
        elif format_type == "xml":
            return XMLHandler().extract(
                response.text, source.get("text_field")
            )
        elif format_type == "html":
            return HTMLHandler().extract(response.text)
        elif format_type == "pdf":
            return PDFHandler().extract(response.content)
        elif format_type == "text":
            return TextHandler().extract(response.text, source.get("text_field"))
        else:
            return response.text


def _build_readable_url(source: dict, doc_id: str, fetch_url: str) -> str:
    """
    Return a human-readable paper URL from the source name + doc_id.
    Falls back to fetch_url only if no pattern matches — avoids storing
    internal API URLs (efetch.fcgi, etc.) as provenance.
    """
    name = source.get("name", "")
    if name == "pmc":
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{doc_id}/"
    if name == "pubmed":
        return f"https://pubmed.ncbi.nlm.nih.gov/{doc_id}/"
    if name == "biorxiv":
        return f"https://www.biorxiv.org/content/{doc_id}"
    if name == "clinicaltrials":
        return f"https://clinicaltrials.gov/study/{doc_id}"
    if name == "geo":
        return f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={doc_id}"
    if name == "www.medrxiv.org":
        return f"https://www.medrxiv.org/content/{doc_id}"
    # For unknown sources: only use fetch_url if it's human-readable (not an API URL)
    if fetch_url and "efetch.fcgi" not in fetch_url and "eutils" not in fetch_url:
        return fetch_url
    return ""


def _is_pdf_url(url: str) -> bool:
    """Return True if the URL looks like a PDF file."""
    return url.lower().endswith(".pdf") or "full.pdf" in url.lower() or "/pdf" in url.lower()


def _recover_blocked_pdf(url: str, document_id: str, log) -> str:
    """
    Attempt to recover a blocked PDF via multiple strategies.
    Returns local file path if successful, empty string otherwise.
    """
    import re, hashlib, subprocess, tempfile
    from pathlib import Path

    pdf_inbox = Path(os.getenv("PDF_INBOX_DIR", "data/pdf_inbox"))
    pdf_inbox.mkdir(parents=True, exist_ok=True)

    # ── Strategy 1: Check pdf_inbox for an already-downloaded copy ────────────
    # Match by sanitised document_id filename or any PDF containing the DOI
    safe_name = re.sub(r"[^\w.-]", "_", document_id)[:80]
    for pattern in [f"{safe_name}.pdf", f"*{safe_name[:20]}*.pdf"]:
        import glob
        matches = glob.glob(str(pdf_inbox / pattern))
        if matches:
            log(f"           ✓ Found existing file in pdf_inbox: {Path(matches[0]).name}")
            return matches[0]

    # ── Strategy 2: Try download with browser-like headers ────────────────────
    log(f"           ↳ Attempting browser-headers download…")
    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "application/pdf,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         url.rsplit("/", 1)[0] + "/",
    }
    try:
        resp = requests.get(url, headers=browser_headers, timeout=30, allow_redirects=True)
        if resp.status_code == 200 and resp.content[:4] == b"%PDF":
            dest = pdf_inbox / f"{safe_name}.pdf"
            dest.write_bytes(resp.content)
            log(f"           ✓ Downloaded via browser-headers ({len(resp.content):,} bytes) → {dest.name}")
            return str(dest)
    except Exception as e:
        log(f"           ✗ Browser-headers download failed: {e}")

    # ── Strategy 3: Try curl (sometimes works when requests doesn't) ──────────
    log(f"           ↳ Attempting curl download…")
    dest_curl = pdf_inbox / f"{safe_name}.pdf"
    try:
        result = subprocess.run(
            ["curl", "-L", "-A", "Mozilla/5.0", "--max-time", "30", "-o", str(dest_curl), url],
            capture_output=True, timeout=35,
        )
        if dest_curl.exists() and dest_curl.stat().st_size > 1000:
            with open(dest_curl, "rb") as f:
                if f.read(4) == b"%PDF":
                    log(f"           ✓ Downloaded via curl ({dest_curl.stat().st_size:,} bytes) → {dest_curl.name}")
                    return str(dest_curl)
        if dest_curl.exists():
            dest_curl.unlink()
    except Exception as e:
        log(f"           ✗ curl download failed: {e}")

    log(f"           ✗ PDF access blocked — automatic download failed")
    log(f"             → Download the PDF manually and place it in: {pdf_inbox}/")
    log(f"             → Then re-run the pipeline — it will pick it up automatically")
    return ""


def _lookup_pmc_id(pmid: str, api_key_env: str = "") -> str:
    """Return the PMC ID for a given PMID via NCBI ID converter, or '' if not found."""
    try:
        url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}&format=json"
        resp = requests.get(url, timeout=10)
        records = resp.json().get("records", [])
        pmcid = records[0].get("pmcid", "") if records else ""
        return pmcid  # e.g. "PMC3836174" or ""
    except Exception:
        return ""


def _find_coref_rewrites(before: str, after: str) -> list:
    """Return list of (before_sentence, after_sentence) pairs that differ."""
    import re
    before_sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', before) if s.strip()]
    after_sents  = [s.strip() for s in re.split(r'(?<=[.!?])\s+', after)  if s.strip()]
    rewrites = []
    for b, a in zip(before_sents, after_sents):
        if b != a:
            rewrites.append((b, a))
    return rewrites