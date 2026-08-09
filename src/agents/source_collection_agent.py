"""
Source Collection Agent
========================
Job: given a vendor name (and optionally a pre-supplied list of public
URLs), produce a clean list of SourceRecord rows to hand to the
Evidence Extraction Agent.

This agent does NOT crawl the web on its own. It works from one of two
inputs, in priority order:

1. A pre-prepared source file (CSV/JSON) supplied by the user - the
   expected mode for a controlled internal experiment, since a human
   has already vetted these URLs as public and appropriate.
2. A small built-in "starter map" of common public page patterns
   (e.g. "<vendor>.com/security", "<vendor>.com/pricing") that the
   agent proposes as candidates for a human to confirm - it never
   fetches or trusts a guessed URL without that page appearing in the
   confirmed source list used by the Evidence Extraction Agent.

Optional category_filter narrows source_type to a subset (e.g. only
"security" and "privacy" sources) for a focused re-run.
"""

from typing import List, Optional
from ..models import SourceRecord, SOURCE_TYPES
from ..extraction_utils import guess_source_type

# category -> which source_types are relevant, used only for filtering
CATEGORY_TO_SOURCE_TYPES = {
    "security": ["security_trust_page"],
    "privacy": ["privacy_policy", "terms_of_service"],
    "pricing": ["pricing_page"],
    "support": ["help_center"],
    "product": ["official_product_page", "blog_release_notes"],
    "integrations": ["integration_page"],
    "uptime": ["status_page"],
    "documentation": ["help_center"],
}


class SourceCollectionAgent:
    name = "source_collection_agent"

    def run(self, vendor_name: str, urls: List[str],
            category_filter: Optional[str] = None) -> List[SourceRecord]:
        """
        vendor_name : e.g. "Linear"
        urls        : list of public URLs a human has already gathered /
                       approved for this vendor
        category_filter : optional, e.g. "security" -> keep only source
                       types relevant to that category
        """
        records = []
        for url in urls:
            source_type = guess_source_type(url)
            records.append(SourceRecord(
                vendor_name=vendor_name,
                source_url=url,
                source_type=source_type,
                category_filter=category_filter,
            ))

        if category_filter and category_filter in CATEGORY_TO_SOURCE_TYPES:
            allowed = set(CATEGORY_TO_SOURCE_TYPES[category_filter])
            records = [r for r in records if r.source_type in allowed]

        return records

    def suggest_candidate_urls(self, vendor_name: str, vendor_domain: str) -> List[str]:
        """
        Propose likely public page paths for a vendor domain. These are
        SUGGESTIONS ONLY for a human to confirm before they are ever
        added to the approved source list - the agent never auto-adds
        guessed URLs to the pipeline.
        """
        domain = vendor_domain.rstrip("/")
        return [
            f"https://{domain}",
            f"https://{domain}/pricing",
            f"https://{domain}/security",
            f"https://{domain}/privacy",
            f"https://{domain}/terms",
            f"https://{domain}/help",
            f"https://{domain}/integrations",
            f"https://status.{domain}",
            f"https://{domain}/blog",
        ]
