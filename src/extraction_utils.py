"""
Utilities for turning a raw web page into a clean text excerpt plus tags.

Two fetch modes:
- "live"  : real HTTP GET via requests, cleaned with trafilatura
            (falls back to BeautifulSoup text extraction if trafilatura
            is not installed or returns nothing useful).
- "local" : reads a pre-saved HTML fixture from disk. Used for the demo
            data in this repo and useful in any environment (like this
            sandbox) with restricted outbound network access.

No page is ever fetched more aggressively than a single GET request.
There is no crawling, no JS rendering, and no bypassing of robots.txt /
paywalls / login screens - this is intentionally a "read the public page
once" tool, not a scraper.

v2 tagging fix (addressing reviewer feedback)
----------------------------------------------
The previous version tagged a whole page at once with naive substring
matching, which caused two concrete bugs:
  1. Substring false positives - "support" matched inside "supported" /
     "supports" / "unsupported", "plan" matched inside unrelated words,
     etc. Fixed by matching single-word keywords on WORD BOUNDARIES
     (regex \\b...\\b) instead of plain `in` substring checks.
  2. One page-level note reused everywhere - if a page matched both
     "security" and "pricing", the SAME sentence was shown under both
     the Security section and the Pricing section, because there was
     only one evidence_note per page. Fixed by tagging at the SENTENCE
     level (tag_sentences) and keeping a separate note per tag
     (build_tag_notes), so each brief section quotes the sentence that
     actually matched that tag, not just "the same sentence from
     whichever tag happened to be checked first."
"""

import os
import re
from dataclasses import dataclass
from typing import Optional, Dict, List

USER_AGENT = "VendorDueDiligenceResearchBot/0.1 (+internal-prototype; contact=ops-team)"
REQUEST_TIMEOUT = 15
THIN_CONTENT_CHAR_THRESHOLD = 120  # below this, flag as possibly JS-rendered / blocked

# Simple, transparent keyword rules. This is intentionally NOT an ML
# classifier: for a first-pass ops tool, an auditable keyword map that a
# non-technical reviewer can read and edit beats a black-box model.
#
# Keywords are matched per-sentence (see tag_sentences). Single-word
# keywords are matched on word boundaries so "support" doesn't match
# "supported"; multi-word phrases and symbols are matched as substrings
# since word-boundary regex doesn't apply cleanly to phrases/symbols.
#
# Some keywords from v1 were removed for being too generic and prone to
# false positives even with word-boundary matching (e.g. bare
# "availability" / "operational" under uptime, which could describe
# almost anything - replaced with more specific phrases).
TAG_KEYWORDS = {
    "security": [
        "security", "encryption", "encrypted", "soc 2", "soc2", "iso 27001",
        "penetration test", "pen test", "vulnerability", "trust center",
        "data breach", "access control", "mfa", "2fa", "sso",
    ],
    "privacy": [
        "privacy policy", "personal data", "gdpr", "ccpa", "data subject",
        "data retention", "opt out", "opt-out", "do not sell",
        "personal information", "data processing",
    ],
    "pricing": [
        "pricing", "per month", "per user", "free tier", "billing",
        "subscription", "$", "/mo", "enterprise plan", "paid plan",
        "free plan", "pricing plan",
    ],
    "support": [
        "help center", "live chat", "ticket", "response time", "sla",
        "customer success", "customer support", "contact support",
    ],
    "integrations": [
        "integration", "api", "webhook", "zapier", "sdk",
        "marketplace", "plugin", "connects with", "connect to", "connects to",
    ],
    "uptime": [
        "uptime", "status page", "incident history", "downtime", "outage",
        "operational status", "service status", "real-time status",
        "post-incident",
    ],
    "documentation": [
        "documentation", "docs", "developer guide", "api reference",
        "getting started", "tutorial", "changelog",
    ],
    "product": [
        "overview", "features", "product", "platform", "solution",
        "use case",
    ],
}

SOURCE_TYPE_HINTS = [
    ("security", "security_trust_page"),
    ("trust", "security_trust_page"),
    ("privacy", "privacy_policy"),
    ("terms", "terms_of_service"),
    ("pricing", "pricing_page"),
    ("plans", "pricing_page"),
    ("help", "help_center"),
    ("support", "help_center"),
    ("docs", "help_center"),
    ("integration", "integration_page"),
    ("status", "status_page"),
    ("blog", "blog_release_notes"),
    ("changelog", "blog_release_notes"),
]


def guess_source_type(url: str) -> str:
    low = url.lower()
    for hint, source_type in SOURCE_TYPE_HINTS:
        if hint in low:
            return source_type
    return "official_product_page"


_ALNUM_EDGE_RE = re.compile(r"^[a-z0-9].*[a-z0-9]$|^[a-z0-9]$")
_boundary_cache: Dict[str, re.Pattern] = {}


def _keyword_matches(keyword: str, text_low: str) -> bool:
    """Match a single keyword (or short phrase) against already-lowercased
    text. Keywords that start and end with an alphanumeric character -
    whether a single word ("support") or a multi-word phrase ("paid
    plan") - are matched on WORD BOUNDARIES so "support" cannot match
    inside "supported", and "paid plan" cannot match inside "paid plans".
    Keywords that start or end with a symbol ($ , /mo, opt-out) fall back
    to plain substring matching, since \\b doesn't apply meaningfully at
    a symbol edge.
    """
    if _ALNUM_EDGE_RE.match(keyword):
        pattern = _boundary_cache.get(keyword)
        if pattern is None:
            pattern = re.compile(r"\b" + re.escape(keyword) + r"\b")
            _boundary_cache[keyword] = pattern
        return bool(pattern.search(text_low))
    return keyword in text_low


def split_sentences(text: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def tag_sentences(text: str) -> Dict[str, List[str]]:
    """Sentence-level tagging: for each tag, return the list of sentences
    in `text` that actually contain one of that tag's keywords.

    This is the core fix for cross-topic bleed - a page can legitimately
    mention several topics, but each tag only "claims" the sentences that
    are actually about it, instead of the whole page (and every sentence
    on it) being labeled with every tag found anywhere on the page.
    """
    sentences = split_sentences(text)
    result: Dict[str, List[str]] = {}
    for tag, keywords in TAG_KEYWORDS.items():
        matches = []
        for sentence in sentences:
            low = sentence.lower()
            if any(_keyword_matches(kw, low) for kw in keywords):
                matches.append(sentence)
        if matches:
            result[tag] = matches
    return result


def build_tag_notes(tag_sentence_map: Dict[str, List[str]], max_len: int = 220) -> Dict[str, str]:
    """One evidence note PER TAG, drawn only from that tag's own matched
    sentences - not a single page-level note reused across tags.
    """
    notes = {}
    for tag, sentences in tag_sentence_map.items():
        chosen = sentences[0].strip()
        if len(chosen) > max_len:
            chosen = chosen[:max_len].rsplit(" ", 1)[0] + "..."
        notes[tag] = chosen
    return notes


def tag_text(text: str) -> list:
    """Backward-compatible helper: which tags does this text match at all
    (used for e.g. the Sources tab's quick source-type guess). Prefer
    tag_sentences()/build_tag_notes() when you also need the evidence text.
    """
    return list(tag_sentences(text).keys())


def clean_whitespace(text: str) -> str:
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_to_sentences(text: str) -> str:
    """Turn a line-broken extraction (titles/headers on their own line,
    no trailing punctuation) into proper sentence-punctuated prose, so
    downstream sentence-splitting doesn't glue a page title/header onto
    the first real sentence.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    out = []
    for ln in lines:
        if not re.search(r"[.!?]\s*$", ln):
            ln = ln + "."
        out.append(ln)
    return " ".join(out)


def make_evidence_note(text: str, tags: list, max_len: int = 220) -> str:
    """General 1-2 sentence note for the whole excerpt (used for the
    Evidence tab's summary line, NOT for per-tag brief sections - those
    use build_tag_notes so each tag gets its own sentence).
    """
    sentences = split_sentences(text)
    if not sentences:
        return text[:max_len]
    chosen = sentences[0]
    for s in sentences:
        low = s.lower()
        for tag in tags:
            if any(_keyword_matches(kw, low) for kw in TAG_KEYWORDS.get(tag, [])):
                chosen = s
                break
    chosen = chosen.strip()
    if len(chosen) > max_len:
        chosen = chosen[:max_len].rsplit(" ", 1)[0] + "..."
    return chosen


@dataclass
class FetchResult:
    html: str
    title: str
    fetched_ok: bool
    method: str  # "live" or "local_fixture"
    error: Optional[str] = None
    final_url: Optional[str] = None   # URL after following redirects (live mode)
    status_code: Optional[int] = None


def fetch_local_fixture(fixture_path: str) -> FetchResult:
    if not os.path.exists(fixture_path):
        return FetchResult(html="", title="", fetched_ok=False,
                            method="local_fixture",
                            error=f"fixture not found: {fixture_path}")
    with open(fixture_path, encoding="utf-8") as f:
        html = f.read()
    title = _extract_title(html)
    return FetchResult(html=html, title=title, fetched_ok=True, method="local_fixture")


def fetch_live(url: str) -> FetchResult:
    """Real single GET request. Handles (and reports) the practical
    failure modes a live crawl actually hits:
      - redirects: requests follows them by default; we record the final
        URL so a reviewer can see the page moved, instead of silently
        treating it as if the original URL had answered directly.
      - timeouts / connection errors / DNS failures: caught, reported in
        .error, never raised up into the pipeline.
      - blocked/error responses (403, 404, 5xx): caught via
        raise_for_status(), reported with the actual status code.
    JS-rendered pages are NOT executed (no headless browser - see
    docs/assumptions_and_limitations.md for why that's out of scope for
    a low-cost prototype); a page that comes back nearly empty after
    text extraction is flagged as thin_content by the caller instead of
    being silently treated as a normal, complete page.
    """
    try:
        import requests
    except ImportError:
        return FetchResult(html="", title="", fetched_ok=False, method="live",
                            error="requests not installed")
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT, allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
        title = _extract_title(html)
        return FetchResult(
            html=html, title=title, fetched_ok=True, method="live",
            final_url=resp.url, status_code=resp.status_code,
        )
    except Exception as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        return FetchResult(html="", title="", fetched_ok=False, method="live",
                            error=str(e), status_code=status_code)


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return clean_whitespace(re.sub(r"<[^>]+>", "", m.group(1)))
    return ""


def html_to_clean_text(html: str) -> str:
    """Best-effort clean text extraction.

    Tries trafilatura first (better boilerplate removal), falls back to
    BeautifulSoup, falls back to a crude regex tag-strip so the pipeline
    never hard-fails just because an optional dependency is missing or
    the HTML is malformed.
    """
    if not html or not html.strip():
        return ""

    # 1. trafilatura
    try:
        import trafilatura
        extracted = trafilatura.extract(html, include_comments=False, include_tables=False)
        if extracted and len(extracted.strip()) > 40:
            return clean_whitespace(extracted)
    except ImportError:
        pass
    except Exception:
        pass

    # 2. BeautifulSoup
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "title", "head"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        return normalize_to_sentences(clean_whitespace(text))
    except ImportError:
        pass
    except Exception:
        pass

    # 3. crude fallback - never raises even on malformed/incomplete HTML
    try:
        text = re.sub(r"<[^>]+>", " ", html)
        return clean_whitespace(text)
    except Exception:
        return ""


def truncate_excerpt(text: str, max_chars: int = 1200) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + " [...]"
