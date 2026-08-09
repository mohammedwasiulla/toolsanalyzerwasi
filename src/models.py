"""
Shared data structures used across all three agents.

Keeping these in one place makes the whole pipeline easy to reason about
for a non-technical reviewer: every record that flows through the system
has a fixed, documented shape.

v2 changes (addressing reviewer feedback):
- EvidenceRecord.tag_notes: each tag a page matched now gets its OWN
  evidence sentence, instead of one page-level note being reused under
  every tag section it happened to match. This is what previously made
  the same sentence show up under both "Security" and "Pricing", etc.
- EvidenceRecord.thin_content / final_url: surfaced so a reviewer can see
  when a live fetch returned very little text (possible JS-rendered page,
  block page, or redirect to something unexpected) instead of silently
  treating a near-empty page the same as a normal one.
- VendorBrief.confidence_level keeps the exact "High"/"Medium"/"Low"
  values required by the project brief. VendorBrief.coverage_label adds
  a plain-language phrase ("Good source coverage" etc.) instead of
  wording like "Verified", which overstated what keyword-matching
  against public pages actually establishes.
"""

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


# Tag vocabulary used to classify evidence. Kept small and fixed on purpose
# so the Brief Review Agent can check "did we find anything for tag X"
# instead of doing open-ended NLP judgement calls.
TAGS = [
    "security",
    "privacy",
    "pricing",
    "support",
    "integrations",
    "uptime",
    "documentation",
    "product",
]

SOURCE_TYPES = [
    "official_product_page",
    "pricing_page",
    "security_trust_page",
    "privacy_policy",
    "terms_of_service",
    "help_center",
    "integration_page",
    "status_page",
    "blog_release_notes",
    "other_public_page",
]

CONFIDENCE_LEVELS = ["High", "Medium", "Low"]

# Plain-language label shown alongside the required High/Medium/Low value.
# "confidence" from keyword-matched public pages is source COVERAGE, not
# verification of the underlying facts - the label says that directly.
COVERAGE_LABELS = {
    "High": "Good source coverage",
    "Medium": "Partial source coverage",
    "Low": "Limited source coverage",
}


@dataclass
class SourceRecord:
    """One row produced by the Source Collection Agent."""
    vendor_name: str
    source_url: str
    source_type: str          # one of SOURCE_TYPES
    category_filter: Optional[str] = None   # e.g. "security" if the run was filtered
    added_by: str = "source_collection_agent"
    date_added: str = field(default_factory=lambda: date.today().isoformat())

    def to_dict(self):
        return asdict(self)


@dataclass
class EvidenceRecord:
    """One row produced by the Evidence Extraction Agent.

    This is the atomic, source-linked unit of evidence. Every fact that
    ends up in a vendor brief must be traceable back to one of these rows.
    """
    vendor_name: str
    source_url: str
    source_type: str
    page_title: str
    collected_text: str        # cleaned excerpt, not the full raw page
    date_collected: str
    tags: list                 # subset of TAGS, found via sentence-level matching
    evidence_note: str         # general 1-2 sentence note, shown in the Evidence tab
    tag_notes: dict            # {tag: sentence-specific note} - one per matched tag,
                                # so each brief section quotes DIFFERENT text instead
                                # of reusing one page-level note everywhere
    extraction_method: str      # "rule_based" or "llm_assisted"
    char_count: int = 0
    thin_content: bool = False  # True if extracted text was suspiciously short
                                 # (possible JS-rendered page / block page / redirect)
    final_url: Optional[str] = None   # URL actually fetched after redirects (live mode only)

    def to_dict(self):
        return asdict(self)


@dataclass
class VendorBrief:
    """Final output of the Brief Review Agent for a single vendor."""
    vendor_name: str
    product_category: str
    sources_used: list                # list of source URLs
    security_and_trust: str
    privacy_and_data_handling: str
    support_and_documentation: str
    integrations_and_api: str
    pricing_and_plans: str
    missing_or_unclear: list          # list of tag names with no evidence
    review_flags: list                # list of human-readable follow-up flags
    evidence_snippets: list           # list of {tag, source_url, note}
    confidence_level: str             # High / Medium / Low (required schema value)
    confidence_score: float           # 0.0-1.0 numeric score behind the level, for audit
    coverage_label: str                # plain-language phrase, e.g. "Good source coverage"
    confidence_basis: str              # short explanation of what the score measures
    generated_date: str
    disclaimer: str = (
        "This is an automated first-pass research aid built from public "
        "sources only. It is not a risk score, compliance determination, "
        "or procurement decision. A human reviewer must verify all findings "
        "before any vendor decision is made."
    )

    def to_dict(self):
        return asdict(self)
