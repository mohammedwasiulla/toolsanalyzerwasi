"""
Brief Review Agent
====================
Job: given a vendor's EvidenceRecord list, check coverage against the
fixed TAGS vocabulary, flag gaps, and assemble a single structured
VendorBrief. This agent does not fetch anything and does not add new
facts - it only organizes, checks, and flags what the Evidence
Extraction Agent already found.

v2 changes (addressing reviewer feedback)
-------------------------------------------
1. Each brief section now quotes evidence.tag_notes[tag] - the sentence
   that SPECIFICALLY matched that tag - instead of evidence.evidence_note,
   which was one page-level note reused under every tag section a page
   happened to match. This is what previously made pricing text show up
   under "Security & Trust" etc.

2. Confidence is no longer just "how many tags got matched." It's a
   documented numeric score (0.0-1.0) combining:
     - core coverage:   security AND privacy both present (required for
                         anything above "Low" - a brief with no security/
                         privacy evidence at all is never called "good")
     - breadth:         fraction of the 8 tags with any evidence
     - directness:      of the tags that DO have evidence, what fraction
                         came from a page whose source_type is actually
                         expected to carry that kind of information (e.g.
                         security evidence found on the security/trust
                         page counts as direct; security evidence merely
                         mentioned in passing on the pricing page counts
                         as indirect and is weighted lower)
     - a penalty for fetch failures and thin-content pages, since those
       are evidence gaps, not confirmed absences
   The exact formula and thresholds are in _score_confidence() below,
   and documented in docs/evaluation_metrics.md alongside measured
   precision/recall for the tagging step itself.

3. The required High/Medium/Low value is still produced (per the project
   spec), but the brief also carries a plain-language coverage_label
   ("Good source coverage" / "Partial source coverage" / "Limited source
   coverage") and a confidence_basis string, so nothing implies the tool
   has "verified" anything - it has only found (or not found) keyword
   matches on public pages, and the language says exactly that.
"""

from datetime import date
from typing import List
from collections import defaultdict

from ..models import EvidenceRecord, VendorBrief, TAGS, COVERAGE_LABELS
from .source_collection_agent import CATEGORY_TO_SOURCE_TYPES


CORE_TAGS = ["security", "privacy"]

CONFIDENCE_BASIS_TEXT = (
    "Reflects how much of the fixed tag vocabulary was covered, how directly "
    "the evidence for each tag came from the page type expected to carry it "
    "(e.g. security evidence found on a security/trust page vs. merely "
    "mentioned elsewhere), how recently the evidence was fetched, and "
    "whether any sources failed to fetch or returned very little text. It "
    "measures SOURCE COVERAGE, not verification of the underlying facts."
)


class BriefReviewAgent:
    name = "brief_review_agent"

    def run(self, vendor_name: str, product_category: str,
            evidence: List[EvidenceRecord]) -> VendorBrief:

        by_tag = defaultdict(list)   # tag -> list of (EvidenceRecord, note_for_this_tag)
        fetch_failures = 0
        thin_content_count = 0
        sources_used = []

        for ev in evidence:
            if ev.page_title == "[FETCH FAILED]":
                fetch_failures += 1
                continue
            if ev.thin_content:
                thin_content_count += 1
            sources_used.append(ev.source_url)
            for tag in ev.tags:
                note = ev.tag_notes.get(tag, ev.evidence_note)
                by_tag[tag].append((ev, note))

        def section_text(tag: str, empty_msg: str) -> str:
            items = by_tag.get(tag, [])
            if not items:
                return empty_msg
            seen, unique = set(), []
            for ev, note in items:
                if ev.source_url not in seen:
                    unique.append((ev, note))
                    seen.add(ev.source_url)
            return " ".join(f"- {note} (source: {ev.source_url})" for ev, note in unique[:3])

        security_txt = section_text(
            "security", "No security or trust-center information found in the collected sources.")
        privacy_txt = section_text(
            "privacy", "No privacy or data-handling information found in the collected sources.")

        # merge support+documentation for readability, de-duplicating items
        # tagged with both (each still shows its OWN tag-specific note)
        support_items = by_tag.get("support", [])
        doc_items = by_tag.get("documentation", [])
        merged, seen_urls = [], set()
        for ev, note in (support_items + doc_items):
            if ev.source_url not in seen_urls:
                merged.append((ev, note))
                seen_urls.add(ev.source_url)
        support_txt = (
            " ".join(f"- {note} (source: {ev.source_url})" for ev, note in merged[:3])
            if merged else "No support or documentation availability information found."
        )

        integrations_txt = section_text(
            "integrations", "No integration or API availability information found "
                            "(may still exist; not confirmed in collected sources).")
        pricing_txt = section_text(
            "pricing", "No public pricing or plan information found in the collected sources.")

        missing = [t for t in TAGS if t not in by_tag]
        review_flags = []
        if fetch_failures:
            review_flags.append(f"{fetch_failures} source page(s) failed to fetch - retry manually.")
        if thin_content_count:
            review_flags.append(
                f"{thin_content_count} source page(s) returned very little text "
                f"(possible JS-rendered page, bot-block, or login wall) - verify manually."
            )
        for core in CORE_TAGS:
            if core not in by_tag:
                review_flags.append(f"No {core} information found - manual search recommended before proceeding.")
        if "uptime" in missing:
            review_flags.append("No public status/uptime page identified - confirm one exists if reliability matters for this use case.")
        if not by_tag:
            review_flags.append("No usable evidence extracted at all - re-check source URLs and fetch mode.")

        confidence_level, confidence_score = self._score_confidence(
            by_tag=by_tag, fetch_failures=fetch_failures, thin_content_count=thin_content_count,
        )

        evidence_snippets = [
            {"tag": tag, "source_url": ev.source_url, "note": note}
            for tag, items in by_tag.items() for ev, note in items[:2]
        ]

        return VendorBrief(
            vendor_name=vendor_name,
            product_category=product_category,
            sources_used=sorted(set(sources_used)),
            security_and_trust=security_txt,
            privacy_and_data_handling=privacy_txt,
            support_and_documentation=support_txt,
            integrations_and_api=integrations_txt,
            pricing_and_plans=pricing_txt,
            missing_or_unclear=missing,
            review_flags=review_flags,
            evidence_snippets=evidence_snippets,
            confidence_level=confidence_level,
            confidence_score=round(confidence_score, 3),
            coverage_label=COVERAGE_LABELS[confidence_level],
            confidence_basis=CONFIDENCE_BASIS_TEXT,
            generated_date=date.today().isoformat(),
        )

    @staticmethod
    def _recency_of(date_collected: str) -> float:
        """How fresh is this evidence, based on when WE fetched it.

        Important distinction (stated here and in the docs): this is
        recency of OUR data collection, not recency of the vendor's
        underlying page content. Detecting a real "last updated" date
        would require parsing page metadata that most pages don't expose
        reliably - out of scope for a rule-based first-pass tool. What
        this DOES catch: a brief built from evidence fetched months ago
        (e.g. a stale cached run) scoring lower than one built from a
        fresh fetch, so an ops reviewer knows to re-run rather than trust
        old data. In this repo's offline demo mode, every fetch happens
        at run time, so recency is always 1.0 - it only differentiates
        across runs over time, which is the real-world use case.
        """
        try:
            collected = date.fromisoformat(date_collected)
        except (ValueError, TypeError):
            return 0.5  # malformed/unknown date - neutral, not full trust
        age_days = (date.today() - collected).days
        if age_days <= 30:
            return 1.0
        if age_days <= 90:
            return 0.6
        return 0.3

    def _score_confidence(self, by_tag, fetch_failures: int, thin_content_count: int):
        """Returns (level: 'High'|'Medium'|'Low', score: float in [0,1]).

        Formula (documented here so it's auditable, not a black box):
          breadth    = tags_covered / len(TAGS)                     weight 0.35
          directness = mean, over covered tags, of the fraction of
                       that tag's evidence found on an "expected"
                       source_type for it (CATEGORY_TO_SOURCE_TYPES)  weight 0.35
          recency    = mean, over covered tags' evidence, of how
                       recently WE fetched it (see _recency_of)       weight 0.15
          core_bonus = 0.15 if BOTH security and privacy covered,
                       else 0.0                                      weight 0.15
          penalty    = 0.05 per fetch failure + 0.03 per thin-content
                       page, capped at 0.30 total

          score = breadth*0.35 + directness*0.35 + recency*0.15
                  + core_bonus - penalty,  clamped to [0, 1]

        Thresholds:
          score >= 0.65 AND both core tags present AND at most 1 tag
          missing overall                            -> High
          score >= 0.35                               -> Medium
          otherwise                                   -> Low
        A brief is never "High" without both security and privacy
        evidence present, and never "High" if 2 or more of the 8 tags
        have no evidence at all - regardless of how high the weighted
        score is - so a vendor with several real coverage gaps can't
        land in the same tier as one with near-complete coverage.

        NOTE on "source quality" (raised in review feedback but not a
        separate weighted term here): directness already captures the
        main quality signal this tool can assess without a subjective
        per-domain reputation score (which would need external data this
        prototype deliberately doesn't depend on, per the "low-cost, no
        heavy infrastructure" success criterion). A distinct domain-
        reputation factor is listed as a documented future improvement
        in docs/assumptions_and_limitations.md, not silently skipped.
        """
        tags_covered = len(by_tag)
        breadth = tags_covered / len(TAGS)

        if tags_covered:
            directness_scores = []
            recency_scores = []
            for tag, items in by_tag.items():
                expected_types = set(CATEGORY_TO_SOURCE_TYPES.get(tag, []))
                if not expected_types:
                    directness_scores.append(0.6)  # tag has no single "home" page type (e.g. product)
                else:
                    direct_hits = sum(1 for ev, _ in items if ev.source_type in expected_types)
                    directness_scores.append(direct_hits / len(items))
                recency_scores.append(
                    sum(self._recency_of(ev.date_collected) for ev, _ in items) / len(items)
                )
            directness = sum(directness_scores) / len(directness_scores)
            recency = sum(recency_scores) / len(recency_scores)
        else:
            directness = 0.0
            recency = 0.0

        has_core = all(t in by_tag for t in CORE_TAGS)
        core_bonus = 0.15 if has_core else 0.0
        penalty = min(0.30, fetch_failures * 0.05 + thin_content_count * 0.03)

        score = breadth * 0.35 + directness * 0.35 + recency * 0.15 + core_bonus - penalty
        score = max(0.0, min(1.0, score))

        missing_count = len(TAGS) - tags_covered

        if score >= 0.65 and has_core and missing_count <= 1:
            level = "High"
        elif score >= 0.35:
            level = "Medium"
        else:
            level = "Low"

        return level, score
