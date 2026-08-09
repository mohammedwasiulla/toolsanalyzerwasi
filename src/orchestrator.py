"""
Orchestrator
=============
Deliberately simple, linear, custom Python orchestration - no manager
agent, no autonomous loop, no shared memory beyond the two lists of
records passed explicitly from one agent to the next.

Source Collection Agent -> Evidence Extraction Agent -> Brief Review Agent

Every run produces a `trace`: an ordered list of plain-English steps
describing what each agent did, so a non-technical reviewer can see and
debug the workflow without reading code.
"""

import os
from typing import List, Optional, Dict
from datetime import datetime

from .models import SourceRecord, EvidenceRecord, VendorBrief
from .agents.source_collection_agent import SourceCollectionAgent
from .agents.evidence_extraction_agent import EvidenceExtractionAgent
from .agents.brief_review_agent import BriefReviewAgent
from . import storage

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
FIXTURES_DIR = os.path.join(BASE_DIR, "fixtures")


class WorkflowRun:
    """Holds the full result of one vendor run: records + trace."""
    def __init__(self, vendor_name: str):
        self.vendor_name = vendor_name
        self.trace: List[Dict] = []
        self.sources: List[SourceRecord] = []
        self.evidence: List[EvidenceRecord] = []
        self.brief: Optional[VendorBrief] = None

    def log(self, agent: str, message: str):
        self.trace.append({
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "agent": agent,
            "message": message,
        })


def run_workflow(vendor_name: str, urls: List[str], product_category: str,
                  category_filter: Optional[str] = None,
                  mode: str = "local") -> WorkflowRun:
    run = WorkflowRun(vendor_name)

    # --- Step 1: Source Collection Agent ---
    collector = SourceCollectionAgent()
    run.log(collector.name, f"Received {len(urls)} candidate URL(s) for '{vendor_name}'.")
    sources = collector.run(vendor_name, urls, category_filter=category_filter)
    run.sources = sources
    run.log(collector.name,
             f"Classified and stored {len(sources)} source(s)"
             + (f" after filtering to category '{category_filter}'." if category_filter else "."))
    for s in sources:
        run.log(collector.name, f"  source_type='{s.source_type}' -> {s.source_url}")

    # --- Step 2: Evidence Extraction Agent ---
    extractor = EvidenceExtractionAgent(mode=mode, fixtures_dir=FIXTURES_DIR)
    run.log(extractor.name, f"Fetching {len(sources)} page(s) in '{mode}' mode (single request per page).")
    evidence = extractor.run(sources)
    run.evidence = evidence
    ok = sum(1 for e in evidence if e.page_title != "[FETCH FAILED]")
    run.log(extractor.name, f"Extracted evidence from {ok}/{len(evidence)} page(s).")
    for e in evidence:
        if e.page_title == "[FETCH FAILED]":
            run.log(extractor.name, f"  FAILED: {e.source_url}")
        else:
            run.log(extractor.name, f"  tags={e.tags or ['(none matched)']} <- {e.source_url}")

    # --- Step 3: Brief Review Agent ---
    reviewer = BriefReviewAgent()
    run.log(reviewer.name, "Checking evidence coverage against tag vocabulary "
                            "(security, privacy, pricing, support, integrations, uptime, documentation, product).")
    brief = reviewer.run(vendor_name, product_category, evidence)
    run.brief = brief
    run.log(reviewer.name, f"Confidence level: {brief.confidence_level} "
                            f"({brief.coverage_label}, score={brief.confidence_score}). "
                            f"Missing/unclear tags: {brief.missing_or_unclear or 'none'}.")
    for flag in brief.review_flags:
        run.log(reviewer.name, f"  FLAG: {flag}")

    return run


def persist_run(run: WorkflowRun):
    """Write sources / evidence / brief to data/ for later inspection or export."""
    safe = run.vendor_name.lower().replace(" ", "_")

    storage.write_csv([s.to_dict() for s in run.sources],
                       os.path.join(DATA_DIR, "sources", f"{safe}_sources.csv"))
    storage.write_csv([e.to_dict() for e in run.evidence],
                       os.path.join(DATA_DIR, "collected", f"{safe}_evidence.csv"))
    storage.write_json([e.to_dict() for e in run.evidence],
                        os.path.join(DATA_DIR, "collected", f"{safe}_evidence.json"))
    if run.brief:
        storage.write_json(run.brief.to_dict(),
                            os.path.join(DATA_DIR, "briefs", f"{safe}_brief.json"))


def brief_to_markdown(brief: VendorBrief) -> str:
    lines = [
        f"# Vendor Research Brief: {brief.vendor_name}",
        "",
        f"**Product / service category:** {brief.product_category}",
        f"**Generated:** {brief.generated_date}",
        f"**Confidence level:** {brief.confidence_level} — *{brief.coverage_label}* "
        f"(score: {brief.confidence_score})",
        f"**What this score measures:** {brief.confidence_basis}",
        "",
        "> " + brief.disclaimer,
        "",
        "## Key Public Sources Used",
    ]
    lines += [f"- {u}" for u in brief.sources_used] or ["- (none)"]
    lines += [
        "",
        "## Security and Trust Information",
        brief.security_and_trust,
        "",
        "## Privacy and Data-Handling References",
        brief.privacy_and_data_handling,
        "",
        "## Support and Documentation Availability",
        brief.support_and_documentation,
        "",
        "## Integration / API Availability",
        brief.integrations_and_api,
        "",
        "## Pricing / Plan Availability",
        brief.pricing_and_plans,
        "",
        "## Missing or Unclear Information",
    ]
    lines += [f"- {t}" for t in brief.missing_or_unclear] or ["- none"]
    lines += ["", "## Review Flags for Manual Follow-Up"]
    lines += [f"- {f}" for f in brief.review_flags] or ["- none"]
    lines += ["", "## Source-Backed Evidence Snippets"]
    for s in brief.evidence_snippets:
        lines.append(f"- **[{s['tag']}]** {s['note']} — {s['source_url']}")
    lines += ["", "---", "*First-pass internal research aid only. Final review must remain manual.*"]
    return "\n".join(lines)
