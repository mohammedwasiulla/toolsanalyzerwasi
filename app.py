"""
Streamlit review interface for the Vendor Due-Diligence Research Workflow
prototype.

Run with:
    streamlit run app.py

Lets a reviewer:
- pick a vendor (from the pre-prepared source file, or add a new one)
- view collected sources
- run (or replay) the 3-agent workflow
- see each agent's step-by-step trace
- inspect extracted evidence
- view the final structured brief
- export the brief as JSON / CSV / Markdown

VISUAL DESIGN NOTE
-------------------
Theme: "case file / audit dossier." The subject matter is due-diligence
research, so the UI leans into that directly rather than a generic
dashboard look:
  - dark ink sidebar = the case file cover (where you set up the request)
  - warm paper main panel = the desk where the brief gets reviewed
  - IBM Plex Mono for source URLs / tags = evidence labels
  - confidence level rendered as a rotated rubber-stamp badge
  - a 3-step tracker at the top mirrors the real, literal pipeline
    (Source Collection -> Evidence Extraction -> Brief Review) - this is
    an actual sequence in the data, not decorative numbering.
All functional logic is unchanged from the previous version - only the
presentation layer changed.
"""

import os
import sys
import json
import csv
import html as html_lib
from io import StringIO

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.orchestrator import run_workflow, persist_run, brief_to_markdown, DATA_DIR
from src.extraction_utils import guess_source_type

SOURCE_FILE = os.path.join(DATA_DIR, "sources", "vendor_source_list.csv")

st.set_page_config(
    page_title="Vendor Due-Diligence Research Workflow",
    page_icon="🗂️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------
# THEME / DESIGN TOKENS — unified dark "case file" theme
# --------------------------------------------------------------------------
SIDEBAR_INK = "#0C151B"       # case-file cover, slightly deeper than the main desk
MAIN_BG = "#121D25"           # main desk, dark ink family (matches sidebar, not paper)
CARD_BG = "#182530"           # card / panel surfaces
CARD_BG_ALT = "#1D2B37"       # expander / input surfaces
BORDER = "#2A3944"            # hairline borders on dark
TEXT_INK = "#ECE7D9"          # primary text - warm paper tone, kept even in dark mode
TEXT_MUTED = "#8A96A0"
TEXT_ON_INK = "#ECE7D9"
TEXT_ON_INK_MUTED = "#8A96A0"
ACCENT_VERIFIED = "#4FB088"   # brighter forest green - readable on dark
ACCENT_FLAG = "#D9A24B"       # brighter amber
ACCENT_LOW = "#E2827D"        # brighter brick/coral red
ACCENT_LINK = "#7FB3D5"       # light teal-blue for links on dark

CONFIDENCE_COLOR = {
    "High": ACCENT_VERIFIED,
    "Medium": ACCENT_FLAG,
    "Low": ACCENT_LOW,
}

THEME_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif;
}}

/* ---------- App background — dark ink, matches the sidebar ---------- */
[data-testid="stAppViewContainer"] {{
    background: {MAIN_BG};
}}
[data-testid="stHeader"] {{
    background: transparent;
}}
[data-testid="stToolbar"] * {{
    color: {TEXT_MUTED} !important;
}}

/* ---------- Sidebar = case file cover ---------- */
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {SIDEBAR_INK} 0%, {CARD_BG} 100%);
    border-right: 1px solid #060B0F;
}}
[data-testid="stSidebar"] * {{
    color: {TEXT_ON_INK} !important;
}}
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] label {{
    color: {TEXT_ON_INK_MUTED} !important;
    font-size: 0.85rem;
}}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
    font-family: 'Space Grotesk', sans-serif !important;
    color: {TEXT_ON_INK} !important;
    letter-spacing: 0.01em;
}}
[data-testid="stSidebar"] hr {{
    border-color: {BORDER} !important;
}}
[data-testid="stSidebar"] [data-testid="stTextArea"] textarea,
[data-testid="stSidebar"] [data-baseweb="select"] > div {{
    background: {CARD_BG_ALT} !important;
    color: {TEXT_ON_INK} !important;
    border: 1px solid {BORDER} !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.78rem !important;
}}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {{
    font-family: 'IBM Plex Mono', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.7rem !important;
    color: #7C8891 !important;
}}

/* Primary run button styled as a stamp-press button */
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {{
    background: {ACCENT_VERIFIED} !important;
    border: none !important;
    border-radius: 3px !important;
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-size: 0.8rem !important;
    padding: 0.65rem 1rem !important;
    color: #0C1712 !important;
    box-shadow: 0 2px 0 rgba(0,0,0,0.45);
}}
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p {{
    color: #0C1712 !important;
}}
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:hover {{
    filter: brightness(1.12);
}}

/* ---------- Sidebar-open hint banner (main area) ---------- */
.sidebar-hint {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    letter-spacing: 0.03em;
    color: {TEXT_MUTED};
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 12px;
    margin-bottom: 1rem;
    width: fit-content;
}}
.sidebar-hint b {{ color: {TEXT_INK}; }}

/* ---------- Headings ---------- */
h1, h2, h3, h4, h5 {{
    font-family: 'Space Grotesk', sans-serif !important;
    color: {TEXT_INK} !important;
}}
p, span, li, label, .stMarkdown, [data-testid="stCaptionContainer"] {{
    color: {TEXT_INK};
}}
[data-testid="stCaptionContainer"] {{
    color: {TEXT_MUTED} !important;
}}
[data-testid="stAppViewContainer"] a {{
    color: {ACCENT_LINK} !important;
}}

/* ---------- Tabs restyled as ledger dividers ---------- */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
    gap: 4px;
    border-bottom: 1px solid {BORDER};
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: {TEXT_MUTED};
    padding: 10px 16px;
}}
[data-testid="stTabs"] [data-baseweb="tab"] p {{
    color: inherit !important;
}}
[data-testid="stTabs"] [aria-selected="true"] {{
    color: {TEXT_INK} !important;
    border-bottom: 2px solid {ACCENT_VERIFIED} !important;
}}
[data-testid="stTabs"] [aria-selected="true"] p {{
    color: {TEXT_INK} !important;
}}

/* ---------- Containers / cards ---------- */
[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {CARD_BG};
    border: 1px solid {BORDER} !important;
    border-radius: 6px !important;
}}

/* ---------- Expanders (evidence index cards) ---------- */
[data-testid="stExpander"] {{
    border: 1px dashed #3C4C58 !important;
    border-radius: 4px !important;
    background: {CARD_BG};
    margin-bottom: 8px;
}}
[data-testid="stExpander"] summary {{
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.82rem !important;
    color: {TEXT_INK} !important;
}}
[data-testid="stExpander"] [data-testid="stTextArea"] textarea {{
    background: {CARD_BG_ALT} !important;
    color: {TEXT_INK} !important;
    border: 1px solid {BORDER} !important;
}}

/* ---------- Metrics ---------- */
[data-testid="stMetric"] {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 10px 14px;
}}
[data-testid="stMetricLabel"] p {{
    font-family: 'IBM Plex Mono', monospace !important;
    text-transform: uppercase;
    font-size: 0.68rem !important;
    letter-spacing: 0.06em;
    color: {TEXT_MUTED} !important;
}}
[data-testid="stMetricValue"] {{
    font-family: 'Space Grotesk', sans-serif !important;
    color: {TEXT_INK} !important;
}}

/* ---------- Alerts ---------- */
[data-testid="stAlert"] {{
    border-radius: 4px;
    font-size: 0.88rem;
    background: {CARD_BG} !important;
    border: 1px solid {BORDER} !important;
}}
[data-testid="stAlert"] p {{
    color: {TEXT_INK} !important;
}}
[data-testid="stAlertContentWarning"] {{ border-left: 3px solid {ACCENT_FLAG} !important; }}
[data-testid="stAlertContentInfo"] {{ border-left: 3px solid {ACCENT_LINK} !important; }}

/* ---------- Buttons (download etc.) ---------- */
[data-testid="stAppViewContainer"] [data-testid="stBaseButton-secondary"] {{
    border: 1px solid {ACCENT_LINK} !important;
    color: {TEXT_INK} !important;
    background: transparent !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.78rem !important;
    border-radius: 3px !important;
}}
[data-testid="stAppViewContainer"] [data-testid="stBaseButton-secondary"] p {{
    color: {TEXT_INK} !important;
}}
[data-testid="stAppViewContainer"] [data-testid="stBaseButton-secondary"]:hover {{
    background: {ACCENT_LINK} !important;
}}
[data-testid="stAppViewContainer"] [data-testid="stBaseButton-secondary"]:hover p {{
    color: {SIDEBAR_INK} !important;
}}

/* ---------- Dataframe wrapper ---------- */
[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER} !important;
    border-radius: 4px;
    overflow: hidden;
}}

/* ---------- Custom components ---------- */
.dossier-eyebrow {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: {TEXT_MUTED};
    margin-bottom: 2px;
}}
.dossier-title {{
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    font-size: 2.1rem;
    color: {TEXT_INK};
    margin: 0 0 2px 0;
    line-height: 1.15;
}}
.dossier-subtitle {{
    color: {TEXT_MUTED};
    font-size: 0.95rem;
    margin-bottom: 1.1rem;
}}

.stepper {{
    display: flex;
    gap: 0;
    margin: 0.4rem 0 1.6rem 0;
    border: 1px solid {BORDER};
    border-radius: 6px;
    overflow: hidden;
    background: {CARD_BG};
}}
.stepper-step {{
    flex: 1;
    padding: 10px 16px;
    border-right: 1px solid {BORDER};
    display: flex;
    align-items: center;
    gap: 10px;
}}
.stepper-step:last-child {{ border-right: none; }}
.stepper-num {{
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    font-size: 0.95rem;
    width: 26px; height: 26px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}}
.stepper-step.done .stepper-num {{ background: {ACCENT_VERIFIED}; color: #0C1712; }}
.stepper-step.pending .stepper-num {{ background: {CARD_BG_ALT}; color: {TEXT_MUTED}; }}
.stepper-label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}
.stepper-step.done .stepper-label {{ color: {TEXT_INK}; }}
.stepper-step.pending .stepper-label {{ color: {TEXT_MUTED}; }}

.tag-chip {{
    display: inline-block;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 2px 8px;
    border-radius: 3px;
    margin: 2px 4px 2px 0;
    background: rgba(79,176,136,0.14);
    color: {ACCENT_VERIFIED};
    border: 1px solid rgba(79,176,136,0.40);
}}
.tag-chip.empty {{
    background: rgba(226,130,125,0.12);
    color: {ACCENT_LOW};
    border-color: rgba(226,130,125,0.38);
}}

.source-url {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem;
    color: {ACCENT_LINK};
    word-break: break-all;
}}

.stamp {{
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    border: 3px double var(--stamp-color);
    color: var(--stamp-color);
    border-radius: 8px;
    padding: 10px 22px;
    transform: rotate(-3deg);
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    text-align: center;
    background: color-mix(in srgb, var(--stamp-color) 12%, transparent);
}}
.stamp .stamp-level {{ font-size: 1.4rem; line-height: 1.1; }}
.stamp .stamp-caption {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem;
    letter-spacing: 0.1em;
    margin-top: 2px;
}}

.flag-line {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.82rem;
    color: {ACCENT_LOW};
    padding: 4px 0;
    border-bottom: 1px dotted {BORDER};
}}
.trace-line {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem;
    padding: 3px 0;
    color: {TEXT_INK};
}}
.trace-time {{ color: {TEXT_MUTED}; margin-right: 8px; }}
.trace-agent {{ font-weight: 600; color: {ACCENT_LINK}; }}

.section-label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: {TEXT_MUTED};
    border-bottom: 1px solid {BORDER};
    padding-bottom: 4px;
    margin: 1.1rem 0 0.5rem 0;
}}
</style>
"""

st.markdown(THEME_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------
# HELPERS
# --------------------------------------------------------------------------
@st.cache_data
def load_source_file(path):
    vendors, categories = {}, {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vendors.setdefault(row["vendor_name"], []).append(row["source_url"])
            categories[row["vendor_name"]] = row.get("product_category", "Unknown")
    return vendors, categories


def esc(text) -> str:
    return html_lib.escape(str(text))


def render_header():
    st.markdown(
        """
        <div class="dossier-eyebrow">Case file &middot; public-source research only</div>
        <div class="dossier-title">Vendor Due-Diligence Dossier</div>
        <div class="dossier-subtitle">Source Collection &rarr; Evidence Extraction &rarr; Brief Review &middot;
        every finding below is source-linked and pending manual sign-off.</div>
        <div class="sidebar-hint">&raquo;&nbsp; <b>Don't see the control panel?</b>&nbsp;
        Click the <b>&raquo;</b> arrow at the top-left corner to open the sidebar —
        that's where you select a vendor and run the workflow.</div>
        """,
        unsafe_allow_html=True,
    )


def render_stepper(run):
    steps = [("01", "Source Collection"), ("02", "Evidence Extraction"), ("03", "Brief Review")]
    done = bool(run)
    parts = []
    for num, label in steps:
        state = "done" if done else "pending"
        mark = "✓" if done else num
        parts.append(
            f'<div class="stepper-step {state}"><div class="stepper-num">{mark}</div>'
            f'<div class="stepper-label">{esc(label)}</div></div>'
        )
    st.markdown(f'<div class="stepper">{"".join(parts)}</div>', unsafe_allow_html=True)


def render_tags(tags):
    if not tags:
        return '<span class="tag-chip empty">no tags matched</span>'
    return "".join(f'<span class="tag-chip">{esc(t)}</span>' for t in tags)


def render_stamp(level: str, coverage_label: str, score: float):
    color = CONFIDENCE_COLOR.get(level, TEXT_MUTED)
    st.markdown(
        f"""
        <div class="stamp" style="--stamp-color:{color};">
            <div class="stamp-level">{esc(level)}</div>
            <div class="stamp-caption">{esc(coverage_label.upper())} &middot; SCORE {score:.2f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# SIDEBAR — the "case file cover"
# --------------------------------------------------------------------------
st.sidebar.markdown(
    '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;'
    'letter-spacing:0.14em;color:#7C8891;margin-bottom:-8px;">FILE OPENED</div>',
    unsafe_allow_html=True,
)
st.sidebar.title("Vendor Due-Diligence")
st.sidebar.caption("Internal prototype · first-pass research aid · manual review required")
st.sidebar.divider()

vendors, categories = load_source_file(SOURCE_FILE)
vendor_names = sorted(vendors.keys())

st.sidebar.markdown("**1 · Select vendor**")
selected_vendor = st.sidebar.selectbox("Vendor", vendor_names, label_visibility="collapsed")

st.sidebar.markdown("**2 · Public source URLs**")
current_urls = vendors[selected_vendor]
url_text = st.sidebar.text_area(
    "Public source URLs", value="\n".join(current_urls), height=170,
    label_visibility="collapsed",
)
edited_urls = [u.strip() for u in url_text.splitlines() if u.strip()]

st.sidebar.markdown("**3 · Category focus (optional)**")
category_filter = st.sidebar.selectbox(
    "Category focus",
    ["(none — full brief)", "security", "privacy", "pricing", "support", "product", "integrations", "uptime"],
    label_visibility="collapsed",
)
category_filter = None if category_filter.startswith("(none") else category_filter

st.sidebar.markdown("**4 · Fetch mode**")
mode = st.sidebar.radio(
    "Fetch mode",
    ["local — bundled demo fixtures", "live — real HTTP request"],
    label_visibility="collapsed",
    help="'local' reads the bundled offline demo pages. 'live' performs a real "
         "single GET request per URL via requests + trafilatura/BeautifulSoup.",
)
mode = "local" if mode.startswith("local") else "live"

run_clicked = st.sidebar.button("▶  Run workflow", type="primary", use_container_width=True)

st.sidebar.divider()
st.sidebar.markdown(
    '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;'
    'line-height:1.5;color:#7C8891;">'
    '⚠ FIRST-PASS AID ONLY — not a risk score, not a procurement decision, '
    'not legal/compliance/security approval. Final review must remain manual.'
    "</div>",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# RUN STATE
# --------------------------------------------------------------------------
if "run_result" not in st.session_state:
    st.session_state.run_result = None

if run_clicked:
    with st.spinner("Running Source Collection → Evidence Extraction → Brief Review..."):
        result = run_workflow(
            vendor_name=selected_vendor,
            urls=edited_urls,
            product_category=categories.get(selected_vendor, "Unknown"),
            category_filter=category_filter,
            mode=mode,
        )
        persist_run(result)
    st.session_state.run_result = result

run = st.session_state.run_result

# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
render_header()
render_stepper(run)

tab_sources, tab_trace, tab_evidence, tab_brief = st.tabs(
    ["Sources", "Agent Trace", "Extracted Evidence", "Vendor Brief"]
)

with tab_sources:
    with st.container(border=True):
        st.markdown(f"##### {esc(selected_vendor)}")
        st.caption(f"Product / service category: {categories.get(selected_vendor, 'Unknown')}")
        st.markdown('<div class="section-label">Collected public sources</div>', unsafe_allow_html=True)
        for u in edited_urls:
            st.markdown(
                f'<div class="trace-line"><span class="tag-chip">{esc(guess_source_type(u))}</span> '
                f'<span class="source-url">{esc(u)}</span></div>',
                unsafe_allow_html=True,
            )
    st.info(
        "Source URLs are supplied by the reviewer (or loaded from "
        "`data/sources/vendor_source_list.csv`). The Source Collection Agent "
        "never adds a URL that wasn't given to it — it only classifies and "
        "(optionally) filters what's here."
    )

with tab_trace:
    if not run:
        st.warning("Click **Run workflow** in the sidebar to see the agent trace.")
    else:
        with st.container(border=True):
            for step in run.trace:
                agent_label = {
                    "source_collection_agent": "SOURCE COLLECTION",
                    "evidence_extraction_agent": "EVIDENCE EXTRACTION",
                    "brief_review_agent": "BRIEF REVIEW",
                }.get(step["agent"], step["agent"].upper())
                st.markdown(
                    f'<div class="trace-line"><span class="trace-time">{esc(step["timestamp"])}</span>'
                    f'<span class="trace-agent">{esc(agent_label)}</span> — {esc(step["message"])}</div>',
                    unsafe_allow_html=True,
                )

with tab_evidence:
    if not run:
        st.warning("Click **Run workflow** in the sidebar to see extracted evidence.")
    else:
        for ev in run.evidence:
            failed = ev.page_title == "[FETCH FAILED]"
            header = f"{'FAILED — ' if failed else ''}{ev.page_title or ev.source_url}"
            with st.expander(f"{header}  ·  {ev.source_type}", expanded=False):
                st.markdown(
                    f'<span class="source-url">{esc(ev.source_url)}</span> '
                    f'&nbsp;·&nbsp; collected {esc(ev.date_collected)} '
                    f'&nbsp;·&nbsp; method: {esc(ev.extraction_method)}',
                    unsafe_allow_html=True,
                )
                st.markdown(render_tags(ev.tags), unsafe_allow_html=True)
                if ev.thin_content:
                    st.markdown(
                        '<div class="flag-line">⚑ Very little text extracted — '
                        'possible JS-rendered page, bot-block, or login wall.</div>',
                        unsafe_allow_html=True,
                    )
                if ev.final_url:
                    st.markdown(
                        f'<div class="flag-line">⚑ Redirected to: '
                        f'<span class="source-url">{esc(ev.final_url)}</span></div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(f"**Evidence note:** {esc(ev.evidence_note)}")
                if ev.tag_notes:
                    st.markdown("**Per-tag evidence** — the exact sentence matched for each tag:")
                    for tag, note in ev.tag_notes.items():
                        st.markdown(
                            f'<div class="trace-line"><span class="tag-chip">{esc(tag)}</span> {esc(note)}</div>',
                            unsafe_allow_html=True,
                        )
                if ev.collected_text:
                    st.text_area("Collected excerpt", ev.collected_text, height=130,
                                 key=f"excerpt_{ev.source_url}", label_visibility="collapsed")

with tab_brief:
    if not run:
        st.warning("Click **Run workflow** in the sidebar to generate the brief.")
    else:
        brief = run.brief
        st.markdown(f"## {esc(brief.vendor_name)}")

        c_stamp, c1, c2 = st.columns([1, 1, 1])
        with c_stamp:
            render_stamp(brief.confidence_level, brief.coverage_label, brief.confidence_score)
        with c1:
            st.metric("Sources used", len(brief.sources_used))
        with c2:
            st.metric("Missing / unclear areas", len(brief.missing_or_unclear))

        st.caption(f"ℹ️ What this score means: {brief.confidence_basis}")

        st.warning(brief.disclaimer)

        st.markdown('<div class="section-label">Key public sources used</div>', unsafe_allow_html=True)
        for u in brief.sources_used:
            st.markdown(f'<div class="source-url">&bull; {esc(u)}</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            with st.container(border=True):
                st.markdown('<div class="section-label">Security & Trust</div>', unsafe_allow_html=True)
                st.write(brief.security_and_trust)
            with st.container(border=True):
                st.markdown('<div class="section-label">Privacy & Data-Handling</div>', unsafe_allow_html=True)
                st.write(brief.privacy_and_data_handling)
            with st.container(border=True):
                st.markdown('<div class="section-label">Support & Documentation</div>', unsafe_allow_html=True)
                st.write(brief.support_and_documentation)
        with col2:
            with st.container(border=True):
                st.markdown('<div class="section-label">Integrations / API</div>', unsafe_allow_html=True)
                st.write(brief.integrations_and_api)
            with st.container(border=True):
                st.markdown('<div class="section-label">Pricing / Plans</div>', unsafe_allow_html=True)
                st.write(brief.pricing_and_plans)
            with st.container(border=True):
                st.markdown('<div class="section-label">Missing or Unclear</div>', unsafe_allow_html=True)
                st.markdown(render_tags(brief.missing_or_unclear), unsafe_allow_html=True)

        st.markdown('<div class="section-label">Review flags for manual follow-up</div>', unsafe_allow_html=True)
        if brief.review_flags:
            for f in brief.review_flags:
                st.markdown(f'<div class="flag-line">⚑ {esc(f)}</div>', unsafe_allow_html=True)
        else:
            st.caption("No flags raised.")

        st.markdown('<div class="section-label">Source-backed evidence snippets</div>', unsafe_allow_html=True)
        st.dataframe(brief.evidence_snippets, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown('<div class="section-label">Export brief</div>', unsafe_allow_html=True)
        safe = brief.vendor_name.lower().replace(" ", "_")
        b1, b2, b3 = st.columns(3)
        b1.download_button(
            "⬇ JSON", data=json.dumps(brief.to_dict(), indent=2),
            file_name=f"{safe}_brief.json", mime="application/json", use_container_width=True,
        )
        b2.download_button(
            "⬇ Markdown", data=brief_to_markdown(brief),
            file_name=f"{safe}_brief.md", mime="text/markdown", use_container_width=True,
        )
        csv_buf = StringIO()
        writer = csv.DictWriter(csv_buf, fieldnames=list(brief.to_dict().keys()))
        writer.writeheader()
        row = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in brief.to_dict().items()}
        writer.writerow(row)
        b3.download_button(
            "⬇ CSV", data=csv_buf.getvalue(),
            file_name=f"{safe}_brief.csv", mime="text/csv", use_container_width=True,
        )
