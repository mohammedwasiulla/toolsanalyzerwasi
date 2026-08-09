"""
Evidence Extraction Agent
==========================
Job: given a list of SourceRecord rows, fetch each page ONCE (either a
real single GET request, or a local fixture file for demo/offline
mode), extract clean text, tag it against the fixed TAGS vocabulary at
the SENTENCE level, and produce an EvidenceRecord per source with one
evidence note PER TAG (not one page-level note reused everywhere).

No page is fetched more than once per run. No JS rendering. No login
walls. If a page fails to fetch, that is recorded as a gap for the
Brief Review Agent to flag - it is never silently skipped. A page that
fetches successfully but returns suspiciously little extractable text
(under THIN_CONTENT_CHAR_THRESHOLD) is flagged thin_content=True instead
of being silently treated as a normal, complete page - this is the
practical signal for "this might be a JS-rendered page, a bot-block
page, or a redirect to something unexpected" without needing a full
headless-browser dependency.
"""

from datetime import date
from typing import List, Optional

from ..models import SourceRecord, EvidenceRecord
from ..extraction_utils import (
    fetch_live, fetch_local_fixture, html_to_clean_text,
    truncate_excerpt, tag_sentences, build_tag_notes, make_evidence_note,
    THIN_CONTENT_CHAR_THRESHOLD,
)
from ..llm_hook import summarize_evidence, llm_available


class EvidenceExtractionAgent:
    name = "evidence_extraction_agent"

    def __init__(self, mode: str = "local", fixtures_dir: Optional[str] = None):
        """
        mode : "live"  -> real HTTP fetch via requests
               "local" -> read matching fixture file from fixtures_dir
        fixtures_dir : required if mode == "local"
        """
        assert mode in ("live", "local")
        self.mode = mode
        self.fixtures_dir = fixtures_dir

    def _fixture_path(self, source: SourceRecord) -> str:
        import re, os
        safe_vendor = re.sub(r"[^a-z0-9]+", "_", source.vendor_name.lower()).strip("_")
        safe_type = source.source_type
        return os.path.join(self.fixtures_dir, f"{safe_vendor}__{safe_type}.html")

    def run(self, sources: List[SourceRecord]) -> List[EvidenceRecord]:
        evidence = []
        for source in sources:
            if self.mode == "live":
                result = fetch_live(source.source_url)
            else:
                result = fetch_local_fixture(self._fixture_path(source))

            if not result.fetched_ok:
                status = f", status={result.status_code}" if result.status_code else ""
                evidence.append(EvidenceRecord(
                    vendor_name=source.vendor_name,
                    source_url=source.source_url,
                    source_type=source.source_type,
                    page_title="[FETCH FAILED]",
                    collected_text="",
                    date_collected=date.today().isoformat(),
                    tags=[],
                    evidence_note=f"Could not retrieve this page ({result.error}{status}). "
                                   f"Flag for manual follow-up.",
                    tag_notes={},
                    extraction_method="none",
                    char_count=0,
                ))
                continue

            clean_text = html_to_clean_text(result.html)
            excerpt = truncate_excerpt(clean_text, max_chars=1200)
            thin_content = len(clean_text.strip()) < THIN_CONTENT_CHAR_THRESHOLD

            tag_sentence_map = tag_sentences(excerpt)
            tags = list(tag_sentence_map.keys())
            tag_notes = build_tag_notes(tag_sentence_map)

            rule_based_note = make_evidence_note(excerpt, tags) if excerpt else (
                "Page fetched but returned little to no extractable text."
            )
            method = "llm_assisted" if llm_available() else "rule_based"
            note = summarize_evidence(source.vendor_name, tags, excerpt, rule_based_note)

            redirected = bool(result.final_url and result.final_url != source.source_url)
            if thin_content:
                note = (note + " [NOTE: page returned very little extractable text - "
                                "possibly JS-rendered, a bot-block page, or requires "
                                "login; verify manually.]")

            evidence.append(EvidenceRecord(
                vendor_name=source.vendor_name,
                source_url=source.source_url,
                source_type=source.source_type,
                page_title=result.title or source.source_type,
                collected_text=excerpt,
                date_collected=date.today().isoformat(),
                tags=tags,
                evidence_note=note,
                tag_notes=tag_notes,
                extraction_method=method,
                char_count=len(excerpt),
                thin_content=thin_content,
                final_url=result.final_url if redirected else None,
            ))
        return evidence
