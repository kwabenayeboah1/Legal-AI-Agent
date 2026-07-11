"""
Streamlit viewer for the case JSON files main.py's batch pipeline writes to
outputs/<case>/*.json (see executor.py's build_output() for their shape).

Independent of JSON_Reader.py — same underlying data, rendered as a dark,
custom-styled dashboard instead of a terminal table. Auto-refreshes every
REFRESH_SECS so newly completed cases from a running batch appear without
restarting Streamlit.

File layout:
  - A large injected <style> block (custom dark theme — Streamlit's own
    widgets are heavily overridden via CSS since the default theme doesn't
    support this layout/density)
  - Constants: paths, refresh interval, and the status->style-class maps
    used throughout rendering
  - Helpers: small formatting/escaping functions shared by every render_*
  - render_sidebar / render_case / render_defendant: the actual page,
    assembled by main() at the bottom
"""
import streamlit as st
import json
from pathlib import Path
from streamlit_autorefresh import st_autorefresh
import html

st.set_page_config(
    page_title="AML Intelligence",
    page_icon="⚖",
    layout="wide",
    initial_sidebar_state="expanded"
)


st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, [class*="css"] {
    font-family: 'Geist', -apple-system, sans-serif;
    background: #050505;
    color: #e8e8e8;
    font-size: 13px;
    line-height: 1.5;
}

/* Force dark background on all Streamlit containers */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMainBlockContainer"],
[data-testid="stBottomBlockContainer"],
[data-testid="stHeader"],
.main, .main > div,
section[data-testid="stSidebar"] ~ div,
[data-testid="stVerticalBlock"] {
    background-color: #050505 !important;
}

#MainMenu, footer, header { visibility: hidden; }

.block-container {
    padding: 1.25rem 1.5rem 3rem 1.5rem !important;
    max-width: 100% !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0a0a0a !important;
    border-right: 1px solid #1c1c1c !important;
    min-width: 260px !important;
    max-width: 260px !important;
}
[data-testid="stSidebar"] > div { padding: 0 !important; }
[data-testid="stSidebar"] * { color: #e8e8e8 !important; }
[data-testid="stSidebar"] .stMultiSelect span,
[data-testid="stSidebar"] .stMultiSelect div { font-size: 12px !important; }

/* ── Inputs ── */
.stTextInput input,
.stTextInput textarea,
[data-testid="stTextInput"] input,
[data-baseweb="input"] input,
[data-baseweb="input"],
[data-baseweb="base-input"],
.stMultiSelect div[data-baseweb="select"],
[data-baseweb="select"] div,
[data-testid="stTextInputRootElement"] {
    background: #111 !important;
    background-color: #111 !important;
    border: 1px solid #1c1c1c !important;
    border-radius: 6px !important;
    color: #e8e8e8 !important;
    font-size: 12px !important;
    font-family: 'Geist', sans-serif !important;
}
.stTextInput input:focus,
[data-baseweb="input"]:focus-within,
[data-baseweb="base-input"]:focus-within {
    border-color: #333 !important;
    outline: none !important;
    background-color: #111 !important;
}

/* Input placeholder text */
.stTextInput input::placeholder,
[data-baseweb="input"] input::placeholder {
    color: #333 !important;
}

/* ── Buttons ── */
.stButton button {
    background: transparent !important;
    border: 1px solid #1c1c1c !important;
    border-radius: 6px !important;
    color: #888 !important;
    font-size: 11px !important;
    font-family: 'Geist Mono', monospace !important;
    padding: 4px 10px !important;
    text-align: left !important;
    transition: all 0.12s ease !important;
    width: 100% !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}
.stButton button:hover {
    background: #111 !important;
    border-color: #333 !important;
    color: #e8e8e8 !important;
}
/* ── Toggle buttons ── */
button[kind="secondary"][data-testid*="toggle_Confirmed"] { color: #ef4444 !important; }
button[kind="secondary"][data-testid*="toggle_Alleged"]   { color: #f97316 !important; }
button[kind="secondary"][data-testid*="toggle_Precedent"] { color: #3b82f6 !important; }
button[kind="secondary"][data-testid*="toggle_Not"]       { color: #555    !important; }

/* ── Expander ── */
[data-testid="stExpander"] {
    background: #0f0f0f !important;
    border: 1px solid #1c1c1c !important;
    border-radius: 6px !important;
    margin-bottom: 10px !important;
    transition: border-color 0.15s ease !important;
}
[data-testid="stExpander"]:hover {
    border-color: #2a2a2a !important;
}
[data-testid="stExpander"] summary {
    font-size: 12px !important;
    color: #aaa !important;
    padding: 8px 12px !important;
}
[data-testid="stExpander"] summary:hover { color: #e8e8e8 !important; }
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
    padding: 0 12px 12px 12px !important;
}
/* Streamlit's internal wrapper divs (markdown containers, vertical blocks)
   can carry their own default background. Since the outer expander's
   border-radius doesn't automatically clip a child's background (and we
   deliberately do NOT use overflow:hidden here — that would also clip the
   .poca-card popout, which needs to render outside this box), force every
   inner wrapper transparent instead so nothing shows through past the
   rounded corner. */
[data-testid="stExpander"] [data-testid="stMarkdownContainer"],
[data-testid="stExpander"] [data-testid="stVerticalBlock"],
[data-testid="stExpander"] [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stExpander"] [data-testid="stElementContainer"],
[data-testid="stExpander"] div[class^="st-"] {
    background: transparent !important;
}
/* Native expander header/toggle chrome — Streamlit's defaults (focus ring,
   icon color, inner button background) don't match a dark custom theme and
   were showing up as a visible mismatched box around the arrow/header. */
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary:focus,
[data-testid="stExpander"] summary:focus-visible,
[data-testid="stExpander"] details > summary::-webkit-details-marker {
    outline: none !important;
    box-shadow: none !important;
    background: transparent !important;
}
[data-testid="stExpander"] svg {
    fill: #555 !important;
    transition: fill 0.15s ease !important;
}
[data-testid="stExpander"]:hover svg {
    fill: #999 !important;
}

/* ── Divider ── */
hr { border: none; border-top: 1px solid #1c1c1c; margin: 0.75rem 0; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: #050505; }
::-webkit-scrollbar-thumb { background: #222; border-radius: 2px; }

/* ── Typography helpers ── */
.mono { font-family: 'Geist Mono', monospace; }
.label {
    font-family: 'Geist Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #444;
    display: block;
    margin-bottom: 4px;
}
.muted { color: #555; font-size: 12px; }
.value { color: #e8e8e8; font-size: 12px; }

/* ── Status dots ── */
.dot-confirmed  { color: #ef4444; }
.dot-alleged    { color: #f97316; }
.dot-precedent  { color: #3b82f6; }
.dot-not-aml    { color: #444; }
.dot-convicted  { color: #ef4444; }
.dot-acquitted  { color: #22c55e; }
.dot-charged    { color: #f97316; }
.dot-mentioned  { color: #444; }

/* ── Case header ── */
.case-title {
    font-size: 16px;
    font-weight: 600;
    color: #f0f0f0;
    line-height: 1.3;
    margin-bottom: 6px;
}
.case-meta {
    display: flex;
    gap: 0;
    align-items: center;
    font-family: 'Geist Mono', monospace;
    font-size: 11px;
    color: #555;
    flex-wrap: wrap;
}
.case-meta-sep { margin: 0 8px; color: #222; }
.case-meta-val { color: #777; }

/* ── Status pill ── */
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 9px;
    border-radius: 4px;
    font-family: 'Geist Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    border: 1px solid;
}
.sp-confirmed { background: #1a0505; color: #ef4444; border-color: #3d0a0a; }
.sp-alleged   { background: #1a0c00; color: #f97316; border-color: #3d1c00; }
.sp-precedent { background: #050d1a; color: #3b82f6; border-color: #0a1f3d; }
.sp-not-aml   { background: #111; color: #555; border-color: #222; }
.sp-convicted { background: #1a0505; color: #ef4444; border-color: #3d0a0a; }
.sp-acquitted { background: #051a0c; color: #22c55e; border-color: #0a3d1c; }
.sp-charged   { background: #1a0c00; color: #f97316; border-color: #3d1c00; }
.sp-mentioned { background: #111; color: #555; border-color: #222; }

/* ── POCA tag & expandable card ── */
.poca-details {
    display: inline-block !important;
    position: relative !important;
    margin-right: 4px !important;
    width: max-content !important;
}
.poca-details[open] {
    z-index: 999 !important;
}

/* Aggressively strip Streamlit defaults */
.poca-details summary,
.poca-details summary::before,
.poca-details summary::after {
    display: inline-block !important;
    list-style: none !important;
    background: transparent !important;
    background-color: transparent !important;
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    box-shadow: none !important;
    width: max-content !important;
    min-height: 0 !important;
    cursor: pointer !important;
    -webkit-tap-highlight-color: transparent !important;
}

/* Kill all hover/focus state backgrounds */
.poca-details summary:hover,
.poca-details summary:focus,
.poca-details summary:active {
    background: transparent !important;
    background-color: transparent !important;
    outline: none !important;
    box-shadow: none !important;
    border: none !important;
}

/* Hide native arrows */
.poca-details summary::-webkit-details-marker {
    display: none !important;
}

/* ── The Tag Itself ── */
.poca-tag {
    display: inline-block !important;
    padding: 1px 7px !important;
    border-radius: 3px !important;
    font-family: 'Geist Mono', monospace !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    background: #100a1a !important;
    color: #a855f7 !important;
    border: 1px solid #2a1040 !important;
    transition: all 0.15s ease !important;
    margin: 0 !important;
}
.poca-tag:hover {
    background: #1a0f2e !important;
    border-color: #a855f7 !important;
}
.poca-details[open] summary .poca-tag {
    background: #a855f7 !important;
    color: #100a1a !important;
}
.poca-details[open] summary .poca-tag-low-confidence {
    background: #f59e0b !important;
    color: #1a1208 !important;
}

/* ── The Expanded Card ── */
.poca-card {
    position: absolute !important;
    top: calc(100% + 6px) !important;
    /* Centered under the tag (rather than left-anchored) so overflow risk is
       split roughly evenly left/right instead of purely rightward — this is
       what caused the card to get clipped at the right edge of narrow
       columns (e.g. the defendant panel), leaving only a sliver visible. */
    left: 50% !important;
    transform: translateX(-50%) !important;
    min-width: 260px !important;
    max-width: min(320px, calc(100vw - 48px)) !important;
    background: #111 !important;
    border: 1px solid #2a1040 !important;
    border-radius: 6px !important;
    padding: 12px !important;
    z-index: 99999 !important;
    box-shadow: 0 8px 24px rgba(0,0,0,0.8) !important;
    color: #ccc !important;
    font-family: 'Geist', sans-serif !important;
    font-size: 11px !important;
    line-height: 1.5 !important;
    white-space: normal !important;
    text-align: left !important;
    cursor: default !important;
    overflow-wrap: anywhere !important;
    word-break: break-word !important;
}
.poca-card-title {
    font-family: 'Geist Mono', monospace !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    color: #a855f7 !important;
    border-bottom: 1px solid #222 !important;
    padding-bottom: 6px !important;
    margin-bottom: 8px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}
.poca-card-body {
    margin-bottom: 10px !important;
    color: #999 !important;
}
.poca-elements {
    margin: 0 0 10px 16px !important;
    padding: 0 !important;
    color: #ddd !important;
}
.poca-elements li {
    margin-bottom: 4px !important;
}
.poca-notes {
    background: #1a1a1a !important;
    border-left: 2px solid #a855f7 !important;
    padding: 6px 8px !important;
    font-size: 10px !important;
    color: #888 !important;
    border-radius: 0 4px 4px 0 !important;
}
/* ── Low-confidence flag ── */
.poca-tag-low-confidence {
    background: #1a1208 !important;
    color: #f59e0b !important;
    border: 1px solid #4a2f08 !important;
}
.poca-tag-low-confidence:hover {
    background: #2a1e0c !important;
    border-color: #f59e0b !important;
}
.poca-confidence-warning {
    background: #1a1208 !important;
    border-left: 2px solid #f59e0b !important;
    padding: 6px 8px !important;
    font-size: 10px !important;
    color: #f59e0b !important;
    border-radius: 0 4px 4px 0 !important;
    margin-bottom: 10px !important;
    font-weight: 600 !important;
}
.poca-confidence-reasoning {
    margin-top: 4px !important;
    font-weight: 400 !important;
    font-style: italic !important;
    color: #d4a04a !important;
}
.poca-part-chapter {
    font-size: 10px !important;
    color: #666 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
    margin-bottom: 8px !important;
}
/* ── Info block ── */
.info-block {
    background: #0a0a0a;
    border: 1px solid #1c1c1c;
    border-radius: 6px;
    padding: 12px 14px;
    margin-bottom: 8px;
    font-size: 12px;
    color: #888;
    line-height: 1.7;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.info-block-label {
    font-family: 'Geist Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #333;
    margin-bottom: 6px;
}

/* ── Section header ── */
.section-hdr {
    font-family: 'Geist Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #333;
    padding-bottom: 6px;
    border-bottom: 1px solid #1c1c1c;
    margin-bottom: 10px;
    margin-top: 14px;
}

/* ── Defendant card ── */
.def-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 4px;
}
.def-name {
    font-size: 12px;
    font-weight: 600;
    color: #e8e8e8;
}
.def-role {
    font-size: 11px;
    color: #555;
    margin-top: 1px;
}

/* ── SIC row ── */
.sic-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid #111;
    gap: 8px;
}
.sic-row:last-child { border-bottom: none; }
.sic-code {
    font-family: 'Geist Mono', monospace;
    font-size: 11px;
    font-weight: 600;
    color: #f59e0b;
    flex-shrink: 0;
    width: 44px;
}
.sic-desc-text {
    font-size: 11px;
    color: #777;
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.sic-conf {
    font-family: 'Geist Mono', monospace;
    font-size: 11px;
    font-weight: 600;
    flex-shrink: 0;
    text-align: right;
    width: 34px;
}

/* ── Conf bar ── */
.conf-bar {
    height: 2px;
    background: #1c1c1c;
    border-radius: 1px;
    margin-top: 3px;
    overflow: hidden;
}
.conf-bar-inner { height: 100%; border-radius: 1px; }

/* ── Finding row ── */
.finding-row {
    display: flex;
    gap: 10px;
    padding: 5px 0;
    border-bottom: 1px solid #111;
    font-size: 11px;
    color: #666;
    line-height: 1.5;
}
.finding-row > span:last-child {
    min-width: 0;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.finding-row:last-child { border-bottom: none; }
.finding-n {
    font-family: 'Geist Mono', monospace;
    color: #333;
    flex-shrink: 0;
    font-size: 10px;
    padding-top: 1px;
}

/* ── Stat bar ── */
.stat-bar {
    display: flex;
    gap: 1px;
    padding: 8px 0;
    border-bottom: 1px solid #1c1c1c;
    margin-bottom: 12px;
}
.stat-item {
    flex: 1;
    padding: 9px 10px 8px 10px;
    background: #0a0a0a;
    border: 1px solid #1c1c1c;
    border-top: 2px solid #333;
    border-radius: 5px;
    margin-right: 6px;
}
.stat-item:last-child { margin-right: 0; }
.stat-item-accent {
    border-top-color: #ef4444 !important;
}
.stat-n {
    font-family: 'Geist Mono', monospace;
    font-size: 19px;
    font-weight: 600;
    color: #e8e8e8;
    display: block;
    line-height: 1.2;
}
.stat-lbl {
    font-family: 'Geist Mono', monospace;
    font-size: 9px;
    color: #444;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 2px;
    display: block;
}

/* ── Sidebar case btn active ── */
.active-case button {
    background: #111 !important;
    border-color: #333 !important;
    color: #e8e8e8 !important;
}

/* ── Key fact ── */
.kf {
    display: flex;
    gap: 8px;
    font-size: 11px;
    color: #666;
    padding: 3px 0;
    line-height: 1.5;
}
.kf > span:last-child {
    min-width: 0;
    overflow-wrap: anywhere;
    word-break: break-word;
}
.kf-arrow { color: #333; flex-shrink: 0; }

/* ── Refresh ── */
.refresh-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-family: 'Geist Mono', monospace;
    font-size: 10px;
    color: #333;
}
.live-dot {
    width: 6px; height: 6px;
    background: #22c55e;
    border-radius: 50%;
    display: inline-block;
    animation: livepulse 2s infinite;
}
@keyframes livepulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.2; }
}

/* Sidebar logo area */
.sidebar-logo {
    padding: 16px 16px 12px 16px;
    border-bottom: 1px solid #1c1c1c;
    margin-bottom: 12px;
}
.logo-row {
    display: flex;
    align-items: center;
    gap: 10px;
}
.logo-icon {
    font-size: 26px;
    line-height: 1;
    color: #e8e8e8;
    flex-shrink: 0;
}
.logo-text {
    font-size: 13px;
    font-weight: 600;
    color: #e8e8e8;
    letter-spacing: -0.01em;
}
.logo-sub {
    font-family: 'Geist Mono', monospace;
    font-size: 10px;
    color: #333;
    margin-top: 1px;
}

/* Sidebar section */
.sb-section { padding: 0 12px 12px 12px; }
.sb-label {
    font-family: 'Geist Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #333;
    padding: 0 4px;
    margin-bottom: 4px;
    display: block;
}

/* Case list item */
.case-list-item {
    padding: 6px 8px;
    border-radius: 5px;
    cursor: pointer;
    border: 1px solid transparent;
    margin-bottom: 2px;
}
.case-list-item:hover { background: #111; border-color: #1c1c1c; }

/* No data */
.empty-state {
    text-align: center;
    padding: 80px 20px;
    color: #333;
}
.empty-icon { font-size: 36px; margin-bottom: 12px; }
.empty-title { font-size: 14px; font-weight: 500; color: #555; margin-bottom: 4px; }
.empty-sub { font-size: 12px; color: #333; }
</style>
""", unsafe_allow_html=True)



# ── Constants ──────────────────────────────────────────────────────────────────

OUTPUT_DIR   = Path("outputs")
REFRESH_SECS = 120  # 120s — aggressive refresh disrupts open expanders

AML_MAP = {
    "Confirmed Verdict": ("sp-confirmed", "● Confirmed Verdict"),
    "Alleged/Charged":   ("sp-alleged",   "● Alleged / Charged"),
    "Precedent Only":    ("sp-precedent", "● Precedent Only"),
    "Not AML":           ("sp-not-aml",   "● Not AML"),
}
VERDICT_MAP = {
    "Convicted":       ("sp-convicted", "● Convicted"),
    "Acquitted":       ("sp-acquitted", "● Acquitted"),
    "Charged/Pending": ("sp-charged",   "● Charged/Pending"),
    "Mentioned Only":  ("sp-mentioned", "● Mentioned Only"),
}
AML_DOT = {
    "Confirmed Verdict": "#ef4444",
    "Alleged/Charged":   "#f97316",
    "Precedent Only":    "#3b82f6",
    "Not AML":           "#444",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=REFRESH_SECS)
def load_cases() -> list[dict]:
    """
    Loads every case JSON under outputs/ (recursively, since batch_process
    groups each case into its own outputs/<case>/ subfolder). Cached for
    REFRESH_SECS so repeated Streamlit reruns between st_autorefresh ticks
    don't re-read the whole tree on every widget interaction; the cache
    naturally picks up newly written files once it expires.
    """
    # Anchor the outputs directory to the location of this script
    BASE_DIR = Path(__file__).parent
    OUTPUT_DIR = BASE_DIR / "outputs"

    if not OUTPUT_DIR.exists():
        return []
        
    cases = []
    
    # rglob searches the outputs folder AND all subfolders
    for f in sorted(OUTPUT_DIR.rglob("*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
                
            if isinstance(data, list):
                cases += [c for c in data if isinstance(c, dict) and "error" not in c]
            elif isinstance(data, dict) and "error" not in data:
                cases.append(data)
                
        except json.JSONDecodeError as e:
            # Alerts you in the terminal if a file is malformed
            print(f"Warning: Could not parse {f.name} - {e}")
        except Exception as e:
            print(f"Warning: Unexpected error reading {f.name} - {e}")
            
    return cases


def safe(text: str) -> str:
    """
    Escape any HTML characters in model-returned text before injecting into markup.

    Two extra protections beyond a plain html.escape():

    1. html.unescape() FIRST, then html.escape() — some source judgment XML (or
       occasionally the model's own output) already contains an HTML/numeric
       entity (e.g. '&#x27;' for an apostrophe, '&amp;' for '&'). Escaping that
       text again without normalizing first double-escapes it, so the entity
       renders as literal visible text (e.g. "Mr. Shah&#x27;s") instead of the
       character it represents. Unescaping first collapses it back to the real
       character, then a single escape pass renders it correctly.

    2. Neutralize literal '$' — Streamlit's markdown layer auto-renders text
       between two '$' as inline LaTeX math, independently of unsafe_allow_html
       (that flag only governs raw HTML tags, not markdown-level LaTeX
       detection). Case text very often contains two dollar amounts in one
       paragraph (e.g. "US$28 million ... US$7 million"), which gets silently
       treated as a math expression — all whitespace between the two '$' signs
       is stripped and the result is italicized. Replacing '$' with its HTML
       entity equivalent prevents the markdown layer from ever seeing a literal
       '$' to match on, while the browser still renders &#36; as a normal '$'.
    """
    if not text:
        return ""
    t = html.unescape(str(text))
    t = html.escape(t)
    t = t.replace('$', '&#36;')
    return t


def parse_conf(raw) -> int:
    """Coerces a SIC confidence value (int, or a string like '85%') to an int clamped to 0-100."""
    try:
        return max(0, min(100, int(str(raw).replace("%", "").strip())))
    except Exception:
        return 0


def conf_color(v: int) -> str:
    """Maps a 0-100 confidence score to a traffic-light colour for the SIC confidence bar/text."""
    if v >= 75: return "#22c55e"
    if v >= 50: return "#f59e0b"
    return "#555"


def pill(text: str, cls: str) -> str:
    """Renders a <span> status pill with the given CSS class (see .status-pill / .sp-* in the style block)."""
    return f'<span class="status-pill {cls}">{safe(text)}</span>'


def aml_pill(status: str) -> str:
    """Case-level AML status pill; falls back to a neutral style for any status not in AML_MAP."""
    cls, label = AML_MAP.get(status, ("sp-not-aml", status or "Unknown"))
    return pill(label, cls)


def verdict_pill(verdict: str) -> str:
    """Per-defendant verdict pill; falls back to a neutral style for any verdict not in VERDICT_MAP."""
    cls, label = VERDICT_MAP.get(verdict, ("sp-mentioned", verdict or "Unknown"))
    return pill(label, cls)


def poca_tag(s: str, enriched: dict | None = None) -> str:
    """
    Render a clickable POCA section tag with an expandable detail card.
    enriched — the case-level poca_sections_enriched dict from the JSON output.
               Falls back gracefully if absent (e.g. older JSON files).
    """
    if not s or s == "N/A":
        return ""

    s_clean = safe(s.strip())
    if "multiple" in s_clean.lower():
        s_clean = "Multiple"

    # Primary source: enriched data embedded in the JSON by executor.py
    info = (enriched or {}).get(s.strip())

    if info:
        title                = safe(info.get("title", ""))
        full                 = safe(info.get("full", ""))
        elements             = [safe(e) for e in info.get("elements", [])]
        notes                = safe(info.get("notes", ""))
        part_chapter         = safe(info.get("part_chapter", ""))
        confidence           = info.get("confidence", "")  # internal flag, not rendered raw
        confidence_reasoning = safe(info.get("confidence_reasoning", ""))
    else:
        # Graceful fallback for old JSONs not yet re-processed
        title                = "Proceeds of Crime Act 2002"
        full                 = f"Re-run the pipeline to embed full reference data for {s_clean}."
        elements             = []
        notes                = ""
        part_chapter         = ""
        confidence           = ""
        confidence_reasoning = ""

    elements_html    = "".join(f"<li>{e}</li>" for e in elements)
    elements_section = f"<ul class='poca-elements'>{elements_html}</ul>" if elements else ""
    notes_section    = f"<div class='poca-notes'><strong>Note:</strong> {notes}</div>" if notes else ""
    part_chapter_section = (
        f"<div class='poca-part-chapter'>{part_chapter}</div>" if part_chapter else ""
    )

    # Low-confidence flag — visible on the tag itself (so it's spottable while
    # scanning a list of cases) and called out inside the card, with the
    # model's own reasoning attached for audit purposes.
    is_low_confidence = confidence.strip().lower() == "low"
    tag_warning_icon  = ' ⚠️' if is_low_confidence else ""
    tag_class         = "poca-tag poca-tag-low-confidence" if is_low_confidence else "poca-tag"
    confidence_reasoning_html = (
        f"<div class='poca-confidence-reasoning'><strong>Why:</strong> {confidence_reasoning}</div>"
        if confidence_reasoning else ""
    )
    confidence_section = (
        "<div class='poca-confidence-warning'>⚠️ Low-confidence reference data — "
        "verify against the Act before relying on this."
        f"{confidence_reasoning_html}</div>"
        if is_low_confidence else ""
    )

    tag_html = f"""
    <details class="poca-details">
        <summary><span class="{tag_class}">{s_clean}{tag_warning_icon}</span></summary>
        <div class="poca-card">
            <div class="poca-card-title">{s_clean} — {title}</div>
            {part_chapter_section}
            {confidence_section}
            <div class="poca-card-body">{full}</div>
            {elements_section}
            {notes_section}
        </div>
    </details>
    """
    return tag_html.replace('\n', '')


def info_block(label: str, text: str) -> str:
    """Renders a labelled prose block (.info-block) — the shared layout for case summary/reasoning sections in render_case."""
    if not text:
        return ""
    return f"""
    <div class="info-block">
        <div class="info-block-label">{safe(label)}</div>
        {safe(text)}
    </div>"""


# ── Sidebar ────────────────────────────────────────────────────────────────────

def render_sidebar(cases: list[dict]) -> list[dict]:
    """
    Renders the sidebar (logo, summary stats, AML-status toggle filters,
    text search, and the clickable case list) and returns the subset of
    `cases` currently passing those filters. The AML-status toggle and the
    currently-selected case both live in st.session_state so they survive
    the periodic st_autorefresh rerun instead of resetting to defaults.
    """
    with st.sidebar:
        st.markdown("""
        <div class="sidebar-logo">
            <div class="logo-row">
                <span class="logo-icon">⚖</span>
                <div>
                    <div class="logo-text">AML Intelligence</div>
                    <div class="logo-sub">Case Results Viewer</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if not cases:
            st.markdown(
                '<div style="padding:12px;color:#333;font-size:12px;">'
                'No cases in outputs/</div>',
                unsafe_allow_html=True
            )
            return []

        # Stats
        total     = len(cases)
        confirmed = sum(1 for c in cases if c.get("aml_status") == "Confirmed Verdict")
        defs      = sum(c.get("defendant_count", 0) for c in cases)
        convicted = sum(
            1 for c in cases
            for d in c.get("defendants", [])
            if d.get("verdict") == "Convicted"
        )
        st.markdown(f"""
        <div style="padding:0 12px 12px 12px;">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                <div class="stat-item">
                    <span class="stat-n">{total}</span>
                    <span class="stat-lbl">Cases</span>
                </div>
                <div class="stat-item stat-item-accent">
                    <span class="stat-n" style="color:#ef4444;">{confirmed}</span>
                    <span class="stat-lbl">Verdicts</span>
                </div>
                <div class="stat-item">
                    <span class="stat-n">{defs}</span>
                    <span class="stat-lbl">Defendants</span>
                </div>
                <div class="stat-item stat-item-accent">
                    <span class="stat-n" style="color:#ef4444;">{convicted}</span>
                    <span class="stat-lbl">Convicted</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<hr style="border-color:#1c1c1c;margin:0 0 12px 0;">', unsafe_allow_html=True)

        # AML status toggles
        all_statuses = sorted({c.get("aml_status", "Unknown") for c in cases})
        if "status_filter" not in st.session_state:
            st.session_state["status_filter"] = set(all_statuses)

        st.markdown('<span class="sb-label" style="padding:0 12px;">AML Status</span>', unsafe_allow_html=True)
        status_filter = []
        for s in all_statuses:
            active = s in st.session_state["status_filter"]
            label  = f"{'✓' if active else '○'}  {s}"
            if st.button(label, key=f"toggle_{s}", use_container_width=True):
                if s in st.session_state["status_filter"]:
                    st.session_state["status_filter"].discard(s)
                else:
                    st.session_state["status_filter"].add(s)
            if s in st.session_state["status_filter"]:
                status_filter.append(s)

        # Search
        st.markdown('<span class="sb-label" style="padding:0 12px;margin-top:10px;display:block;">Search</span>', unsafe_allow_html=True)
        search = st.text_input(
            "search",
            placeholder="Name or reference...",
            label_visibility="collapsed",
            key="search_input"
        )

        st.markdown('<hr style="border-color:#1c1c1c;margin:8px 0;">', unsafe_allow_html=True)

        # Filter cases
        filtered = [
            c for c in cases
            if c.get("aml_status") in status_filter
            and (
                not search
                or search.lower() in (c.get("case_name") or "").lower()
                or search.lower() in (c.get("case_reference") or "").lower()
            )
        ]

        # Case list
        st.markdown(
            f'<span class="sb-label" style="padding:0 16px;">Cases ({len(filtered)})</span>',
            unsafe_allow_html=True
        )

        selected_ref = st.session_state.get("selected_case", "")

        for c in filtered:
            ref    = c.get("case_reference") or c.get("source_file", "—")
            status = c.get("aml_status", "")
            dcount = c.get("defendant_count", 0)
            is_active = ref == selected_ref

            if is_active:
                st.markdown('<div class="active-case">', unsafe_allow_html=True)
            if st.button(
                ref[:32],
                key=f"case_{ref}",
                use_container_width=True,
                help=f"{status} · {dcount} defendant(s)"
            ):
                st.session_state["selected_case"] = ref
            if is_active:
                st.markdown('</div>', unsafe_allow_html=True)

        st.markdown(f"""
        <div style="padding:16px 16px 8px 16px;">
            <span class="refresh-badge">
                <span class="live-dot"></span>
                Auto-refresh {REFRESH_SECS}s
            </span>
        </div>
        """, unsafe_allow_html=True)

    return filtered


# ── Case view ──────────────────────────────────────────────────────────────────

def render_case(case: dict):
    """
    Renders the full detail view for one selected case: header (title,
    status pill, POCA tags, metadata row, parties), then a two-column body
    — left column for case-level prose (summary, AML/POCA reasoning, key
    findings), right column for the list of defendants (each delegated to
    render_defendant).
    """
    name       = safe(case.get("case_name") or "Untitled")
    ref        = safe(case.get("case_reference") or "—")
    court      = safe(case.get("court") or "—")
    juris      = safe(case.get("jurisdiction") or "—")
    date       = safe(case.get("case_date") or "—")
    status     = safe(case.get("aml_status") or "—")
    judge      = safe(case.get("judge") or "")
    docket     = safe(case.get("docket_number") or "")
    source     = safe(case.get("source_file") or "")
    def_count  = case.get("defendant_count", 0)

    poca_sections = case.get("poca_sections") or []
    poca_enriched = case.get("poca_sections_enriched") or {}
    poca_tags_html = "".join(poca_tag(s, poca_enriched) for s in poca_sections)

    # ── Case header ────────────────────────────────────────────────────────────
    badge_row = (
        f'<div style="display:flex;align-items:center;gap:8px;'
        f'flex-wrap:wrap;margin-bottom:6px;">'
        f'{aml_pill(status)}{poca_tags_html}'
        f'</div>'
    )

    # Primary meta row: ref · court · jurisdiction · date
    meta_parts = [
        f'<span class="mono" style="color:#555;">{ref}</span>',
        f'<span class="case-meta-sep">·</span><span class="case-meta-val">{court}</span>',
        f'<span class="case-meta-sep">·</span><span class="case-meta-val">{juris}</span>',
        f'<span class="case-meta-sep">·</span><span class="case-meta-val">{date}</span>',
    ]
    if judge:
        meta_parts.append(
            f'<span class="case-meta-sep">·</span>'
            f'<span class="case-meta-val" title="Presiding Judge">{judge}</span>'
        )
    if docket:
        meta_parts.append(
            f'<span class="case-meta-sep">·</span>'
            f'<span style="font-family:\'Geist Mono\',monospace;font-size:11px;color:#444;" '
            f'title="Docket Number">{docket}</span>'
        )
    if def_count:
        meta_parts.append(
            f'<span class="case-meta-sep">·</span>'
            f'<span style="font-family:\'Geist Mono\',monospace;font-size:11px;color:#444;">'
            f'{def_count} defendant(s)</span>'
        )
    if source:
        meta_parts.append(
            f'<span class="case-meta-sep">·</span>'
            f'<span style="font-family:\'Geist Mono\',monospace;font-size:10px;color:#333;" '
            f'title="Source File">{source}</span>'
        )
    meta_row = f'<div class="case-meta">{"".join(meta_parts)}</div>'

    # Parties row — small muted pill list if present
    parties = case.get("parties") or []
    parties_html = ""
    if parties:
        party_pills = "".join(
            f'<span style="display:inline-block;padding:1px 7px;margin:2px 3px 2px 0;'
            f'border:1px solid #1c1c1c;border-radius:3px;font-size:10px;'
            f'font-family:\'Geist Mono\',monospace;color:#555;">'
            f'{safe(p)}</span>'
            for p in parties
        )
        parties_html = (
            f'<div style="margin-top:6px;line-height:1.8;">{party_pills}</div>'
        )

    st.markdown(
        f'<div style="padding-bottom:12px;border-bottom:1px solid #1c1c1c;margin-bottom:14px;">'
        f'<div class="case-title">{name}</div>'
        f'{badge_row}'
        f'{meta_row}'
        f'{parties_html}'
        f'</div>',
        unsafe_allow_html=True
    )

    # ── Two column layout ──────────────────────────────────────────────────────
    left, right = st.columns([58, 42], gap="large")

    with left:
        # Summary
        summary = case.get("case_summary") or ""
        if summary:
            st.markdown(
                info_block("Summary", summary),
                unsafe_allow_html=True
            )

        # AML reasoning
        aml_r = case.get("aml_status_reasoning") or ""
        if aml_r:
            st.markdown(
                info_block("AML Classification Reasoning", aml_r),
                unsafe_allow_html=True
            )

        # POCA sections — enriched reference table
        if poca_sections and poca_enriched:
            with st.expander(f"POCA 2002 Sections Cited ({len(poca_sections)})", expanded=False):
                for s in poca_sections:
                    info = poca_enriched.get(s, {})
                    s_title   = safe(info.get("title", ""))
                    s_full    = safe(info.get("full", ""))
                    s_elems   = [safe(e) for e in info.get("elements", [])]
                    s_notes   = safe(info.get("notes", ""))
                    el_html   = "".join(f"<li>{e}</li>" for e in s_elems)
                    notes_html = (
                        '<div style="background:#111;border-left:2px solid #a855f7;'
                        'padding:5px 8px;margin-top:6px;font-size:10px;color:#666;">'  
                        f'{s_notes}</div>'
                    ) if s_notes else ""
                    st.markdown(
                        f'<div style="padding:8px 0;border-bottom:1px solid #111;">'
                        f'<div style="display:flex;gap:8px;align-items:baseline;margin-bottom:4px;">'
                        f'<span style="font-family:\'Geist Mono\',monospace;font-size:11px;'
                        f'font-weight:600;color:#a855f7;">{safe(s)}</span>'
                        f'<span style="font-size:11px;color:#aaa;font-weight:500;">{s_title}</span>'
                        f'</div>'
                        f'<div style="font-size:11px;color:#555;line-height:1.6;margin-bottom:4px;">{s_full}</div>'
                        f'<ul style="margin:4px 0 0 16px;padding:0;font-size:11px;color:#777;">{el_html}</ul>'
                        f'{notes_html}</div>',
                        unsafe_allow_html=True
                    )

        # POCA analysis
        poca_a = case.get("poca_analysis") or ""
        if poca_a:
            with st.expander("POCA 2002 Analysis", expanded=False):
                st.markdown(
                    f'<div style="font-size:12px;color:#777;line-height:1.7;">{safe(poca_a)}</div>',
                    unsafe_allow_html=True
                )

        # Precedent
        precedent = case.get("precedent_value") or ""
        if precedent:
            with st.expander("Precedent Value", expanded=False):
                st.markdown(
                    f'<div style="font-size:12px;color:#777;line-height:1.7;">{safe(precedent)}</div>',
                    unsafe_allow_html=True
                )

        # Key findings
        findings = case.get("key_findings") or []
        if findings:
            st.markdown(
                '<div class="section-hdr">Key Findings</div>',
                unsafe_allow_html=True
            )
            rows = "".join(
                f'<div class="finding-row">'
                f'<span class="finding-n">{str(i+1).zfill(2)}</span>'
                f'<span>{safe(f)}</span></div>'
                for i, f in enumerate(findings)
            )
            st.markdown(rows, unsafe_allow_html=True)

    with right:
        defendant_container = st.container()

        defendants = case.get("defendants") or []
        count = len(defendants)

        defendant_container.markdown(
            f'<div class="section-hdr" style="margin-top:0;">Defendants ({count})</div>',
            unsafe_allow_html=True
        )

        if not defendants:
            defendant_container.markdown(
                '<div class="muted">No defendants extracted.</div>',
                unsafe_allow_html=True
            )
        else:
            for idx, d in enumerate(defendants):
                with defendant_container:
                    render_defendant(d, idx, ref, poca_enriched)


def render_defendant(d: dict, idx: int, case_ref: str, poca_enriched: dict | None = None):
    """
    Renders one defendant as a collapsed-by-default expander: role, verdict
    + POCA section pills, verdict/POCA reasoning, key facts, and SIC code
    breakdown with confidence bars. poca_enriched is threaded through from
    render_case so poca_tag() can render the same detail card for a
    defendant's individual section as for the case-level POCA tags.
    """
    name    = safe(d.get("name") or "Unknown")
    role    = safe(d.get("role") or "—")
    verdict = d.get("verdict") or "—"
    poca    = d.get("poca_section") or "N/A"
    sics    = d.get("sic_codes") or []
    facts   = d.get("key_facts") or []
    v_r     = safe(d.get("verdict_reasoning") or "")
    p_r     = safe(d.get("poca_section_reasoning") or "")
    overall = safe(d.get("sic_overall_reasoning") or "")

    label = f"{idx+1:02d} · {d.get('name') or 'Unknown'}"

    with st.expander(label, expanded=False):

        # Role shown at top inside expander
        st.markdown(
            f'<div style="font-size:11px;color:#555;margin-bottom:10px;">{role}</div>',
            unsafe_allow_html=True
        )

        # Verdict + POCA — pass enriched dict so the tag card has full data
        st.markdown(
            f'<div style="display:flex;gap:6px;align-items:center;'
            f'margin-bottom:10px;flex-wrap:wrap;">'
            f'{verdict_pill(verdict)}'
            f'{poca_tag(poca, poca_enriched)}'
            f'</div>',
            unsafe_allow_html=True
        )

        # Verdict reasoning
        if v_r:
            st.markdown(
                f'<div class="info-block-label">Verdict Reasoning</div>'
                f'<div style="font-size:11px;color:#666;line-height:1.6;'
                f'margin-bottom:8px;">{v_r}</div>',
                unsafe_allow_html=True
            )

        # POCA reasoning
        if p_r and poca != "N/A":
            st.markdown(
                f'<div class="info-block-label">POCA Reasoning</div>'
                f'<div style="font-size:11px;color:#666;line-height:1.6;'
                f'margin-bottom:8px;">{p_r}</div>',
                unsafe_allow_html=True
            )

        # Key facts
        if facts:
            st.markdown(
                '<div class="info-block-label">Key Facts</div>',
                unsafe_allow_html=True
            )
            items = "".join(
                f'<div class="kf"><span class="kf-arrow">→</span>'
                f'<span>{safe(f)}</span></div>'
                for f in facts
            )
            st.markdown(
                f'<div style="margin-bottom:8px;">{items}</div>',
                unsafe_allow_html=True
            )

        # SIC codes
        if sics:
            st.markdown(
                f'<div class="info-block-label">SIC Codes ({len(sics)})</div>',
                unsafe_allow_html=True
            )
            rows = ""
            for sic in sics:
                code   = safe(sic.get("code") or "—")
                desc   = safe(sic.get("description") or "—")
                conf   = parse_conf(sic.get("confidence", 0))
                color  = conf_color(conf)
                reason = safe(sic.get("reasoning") or "")
                rows += f"""
                <div class="sic-row">
                    <span class="sic-code">{code}</span>
                    <span class="sic-desc-text" title="{desc}">{desc}</span>
                    <span class="sic-conf" style="color:{color};">{conf}%</span>
                </div>
                <div class="conf-bar" style="margin-bottom:2px;">
                    <div class="conf-bar-inner"
                         style="width:{conf}%;background:{color};"></div>
                </div>
                """
                if reason:
                    rows += (
                        f'<div style="font-size:10px;color:#444;line-height:1.5;'
                        f'margin-bottom:6px;padding-left:44px;">{reason}</div>'
                    )
            st.markdown(rows, unsafe_allow_html=True)

        if overall:
            st.markdown(
                f'<div class="info-block-label" style="margin-top:6px;">'
                f'Overall SIC Reasoning</div>'
                f'<div style="font-size:11px;color:#555;line-height:1.6;">'
                f'{overall}</div>',
                unsafe_allow_html=True
            )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    """
    Page entry point: sets up auto-refresh, loads + filters cases via the
    sidebar, picks which case is "selected" (persisted in session_state,
    defaulting to the first filtered case), and renders it — or an
    empty/no-match state if there's nothing to show.
    """
    st_autorefresh(
        interval=REFRESH_SECS * 1000, 
        key="aml_refresh"
        )

    cases    = load_cases()
    filtered = render_sidebar(cases)

    if not cases:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-icon">⚖</div>
            <div class="empty-title">No cases loaded</div>
            <div class="empty-sub">Run main.py — results will appear automatically</div>
        </div>
        """, unsafe_allow_html=True)
        return

    selected_ref = st.session_state.get("selected_case")

    if not selected_ref and filtered:
        selected_ref = (
            filtered[0].get("case_reference")
            or filtered[0].get("source_file")
        )
        st.session_state["selected_case"] = selected_ref

    selected = next(
        (c for c in filtered
         if (c.get("case_reference") or c.get("source_file")) == selected_ref),
        filtered[0] if filtered else None
    )

    if selected:
        render_case(selected)
    elif filtered:
        render_case(filtered[0])
    else:
        st.markdown(
            '<div class="muted" style="padding:2rem;">No cases match the current filters.</div>',
            unsafe_allow_html=True
        )


if __name__ == "__main__":
    main()
