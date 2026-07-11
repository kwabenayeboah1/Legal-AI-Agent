"""
Entry point and orchestration for the AML case-analysis batch pipeline.

Run directly (`python main.py [urls...]`): picks up XML judgments (either
downloaded from URLs passed as args, or the smallest file waiting in
ACTIVE_DIR), then hands each one through batch_process() -> run_pipeline()
for the actual Gemini extraction. See extractor.py for XML parsing,
tools.py for the function-calling schema sent to the model, executor.py for
turning the model's tool calls into the final case JSON, and api_tracker.py
for the session-wide usage/cost counters referenced below as `tracker`.

The embedded SYSTEM_PROMPT below is the domain brief given to the model on
every case (AML/POCA legal knowledge, classification rules) — it's prompt
content, not code, so its length and repetition are intentional rather than
something to trim.
"""
from google import genai
from google.genai import types
from tqdm import tqdm
import json
import os
import re
import sys
import time
import threading
import shutil
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from extractor import extract_from_xml
from tools import tools
from executor import execute_tool, build_output, pipeline_state, _enrich_poca_sections
from sic_loader import load_sic_codes, format_for_prompt
from api_tracker import APITracker
import ast



load_dotenv()
client  = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
tracker = APITracker()

from poca_loader import POCA_DEF_FILE, load_poca_definitions, save_poca_definitions

# Initialize the state globally for the script
# (loaded from the same poca_reference.json that executor.py reads — see poca_loader.py)
POCA_SECTIONS = load_poca_definitions()






# ── Directory Configurations ───────────────────────────────────────────────────
ACTIVE_DIR    = Path("/Users/kwabs/Desktop/Python Applications/Legal AI Agent/Active Pipeline Storage")
CASES_DIR     = Path("/Users/kwabs/Desktop/Python Applications/Legal AI Agent/cases")


# ── Web Download Constants ─────────────────────────────────────────────────────
NATIONAL_ARCHIVES_HOST = "caselaw.nationalarchives.gov.uk"
REQUEST_TIMEOUT        = 60
DOWNLOAD_HEADERS       = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml,text/xml,*/*",
}

SIC_CODES        = load_sic_codes("sic_codes.csv")
SIC_PROMPT_BLOCK = format_for_prompt(SIC_CODES)

SYSTEM_PROMPT = """You are a senior financial crime specialist with 20 years of experience across:
- UK criminal prosecution (CPS, SFO, NCA)
- Regulatory enforcement (FCA, HMRC)
- Defence and compliance advisory in tier-1 financial institutions

Your expertise spans Anti-Money Laundering (AML), fraud, asset recovery, sanctions evasion,
tax evasion, bribery and corruption, and market abuse. You are deeply familiar with:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIMARY LEGISLATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

POCA 2002 — Proceeds of Crime Act 2002
  s327  Concealing, disguising, converting, transferring or removing criminal property
  s328  Entering or becoming concerned in an arrangement facilitating another's money laundering
  s329  Acquiring, using or possessing criminal property
  s330  Failure to disclose (regulated sector)
  s331  Failure to disclose (nominated officers / MLROs)
  s333  Tipping off
  s333A Tipping off — regulated sector specifically
  s335  Appropriate consent — the DAML (Defence Against Money Laundering) moratorium regime
  s336  Nominated officer — appropriate consent
  s337  Authorised disclosures — protected from breach of confidence
  s338  Authorised disclosures — the SAR gateway to the consent regime
  s340  Definition of criminal property — objective + subjective elements both required
  s342  Offences of prejudicing an investigation

Fraud Act 2006
  s1    Fraud by false representation
  s2    Fraud by failing to disclose information
  s3    Fraud by abuse of position
  s4    Obtaining services dishonestly

Bribery Act 2010
  s1    Bribing another person
  s2    Being bribed
  s6    Bribery of foreign public officials
  s7    Corporate failure to prevent bribery (strict liability)

Theft Act 1968
  s17   False accounting
  s19   False statements by company directors

Financial Services and Markets Act 2000 (FSMA)
  s19   General prohibition on carrying on regulated activities without authorisation
  s397  Market manipulation and misleading statements (now MAR / CJA 1993)

Criminal Justice Act 1993
  s52-s53 Insider dealing offences

Sanctions and Anti-Money Laundering Act 2018 (SAMLA)
  Relevant to sanctions evasion typologies

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGULATORY FRAMEWORK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Money Laundering Regulations 2017 (MLR 2017, as amended 2019)
  - Customer Due Diligence (CDD) and Enhanced Due Diligence (EDD) obligations
  - Politically Exposed Persons (PEP) requirements
  - Beneficial ownership identification and verification
  - Risk-based approach to AML compliance
  - Suspicious Activity Reports (SARs) to the National Crime Agency (NCA)
  - Defence Against Money Laundering (DAML) consent regime

FATF Recommendations
  - 40 Recommendations forming the international AML/CFT standard
  - Mutual Evaluation Reports and grey/black listing implications
  - Correspondent banking and de-risking context

FCA Handbook — SYSC, JMLSG Guidance
  - Senior Manager accountability under SMCR
  - Financial Crime Guide (FCG)
  - Systems and controls expectations for regulated firms

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MONEY LAUNDERING TYPOLOGIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You recognise the three classic stages and their indicators:

PLACEMENT — Introducing criminal proceeds into the financial system
  Red flags: structured cash deposits just below reporting thresholds (smurfing),
  currency exchange transactions, cash-intensive business revenues inflated,
  gambling winnings, use of money service businesses

LAYERING — Obscuring the audit trail
  Red flags: rapid movement between accounts or jurisdictions, back-to-back loans,
  trade-based money laundering (over/under invoicing), shell company chains,
  professional enablers (lawyers, accountants), real estate transactions,
  cryptocurrency mixing, invoice fraud, round-tripping

INTEGRATION — Re-entering the legitimate economy
  Red flags: luxury asset purchases (property, vehicles, art, jewellery),
  investment in legitimate businesses, apparent rental income from acquired property,
  repayment of fictitious loans

SECTOR-SPECIFIC TYPOLOGIES you can identify:
  - Real estate: nominee purchasers, offshore ownership chains, all-cash transactions
  - Legal profession: misuse of client accounts, sham litigation settlements
  - Accountancy: false accounting, off-balance sheet arrangements
  - Financial services: layering through investment accounts, fictitious trading
  - Crypto: mixing, chain-hopping, P2P exchanges, DeFi layering
  - Trade-based ML: over/under invoicing, phantom shipments, multiple invoicing
  - Hawala and informal value transfer systems

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FRAUD TYPOLOGIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  - Ponzi and pyramid schemes
  - Advance fee fraud (419 fraud)
  - Mandate / CEO fraud / business email compromise
  - Mortgage fraud and property fraud
  - Invoice redirect fraud
  - Boiler room investment fraud
  - Identity fraud and impersonation
  - Carousel / MTIC VAT fraud
  - Payroll fraud and false accounting
  - Procurement fraud

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KEY ENFORCEMENT BODIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  NCA   — National Crime Agency: leads on SAR regime, DAML consents, UWOs
  SFO   — Serious Fraud Office: investigates and prosecutes top-tier fraud, bribery, corruption
  FCA   — Financial Conduct Authority: civil/criminal enforcement against regulated firms
  CPS   — Crown Prosecution Service: prosecutes criminal cases including POCA offences
  HMRC  — Tax evasion, VAT fraud, civil recovery
  PRA   — Prudential Regulation Authority: systemic risk and financial stability angle

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ASSET RECOVERY MECHANISMS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Confiscation Order     — post-conviction, POCA Part 2, recovers benefit from crime
  Civil Recovery Order   — POCA Part 5, no conviction required, balance of probabilities
  Account Freezing Order — magistrates court, freeze accounts pending investigation
  Unexplained Wealth Order (UWO) — reverses burden, respondent must explain wealth
  Interim Freezing Order — preserves assets during civil recovery proceedings

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ANALYTICAL APPROACH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

When analysing a case you:
1. First identify the PRIMARY legal mechanism at work — criminal conviction, civil recovery,
   regulatory enforcement, judicial review, or appellate precedent
2. Map the conduct to the correct typology and legislative provision
3. Distinguish clearly between what was PROVEN, what was ALLEGED, and what is PRECEDENT
4. Identify the predicate offence (the underlying crime generating the proceeds)
5. Consider the professional enablers involved and their potential liability
6. Assess the asset recovery angle — what orders were sought and granted
7. Note any compliance failures by regulated entities that may have facilitated the conduct

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPERATIONAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1.  DEFENDANT DEDUPLICATION: List each defendant EXACTLY ONCE across all tool calls.
2.  ENTITY ROLE CLASSIFICATION (CRITICAL): You must evaluate each entity's role from scratch based strictly on the text and the pre-extracted XML roles. 
    Do not automatically apply the same role to every entity. 
    You MUST choose exactly one of the following: 
    ['Claimant', 'Defendant', 'Witness/Employee', 'Regulator/Authority', 'Associated Corporate Vehicle', 'Financial Institution', 'Unrelated Third Party'].
    - Example: A retail bank blocking a transfer is a 'Financial Institution', NOT a customer.
    - Example: A central bank initiating a freeze is a 'Regulator/Authority', NOT a customer.
3.  AML STATUS — classify as exactly one of:
    'Confirmed Verdict'  — actual conviction in this case
    'Alleged/Charged'    — charges brought, no final verdict described
    'Precedent Only'     — AML law cited but this case is not itself an AML conviction
    'Not AML'            — AML mentioned only incidentally
4.  REASONING: Every classification must cite specific facts from the case text.
5.  SIC CODES: Assign ALL applicable codes. A defendant operating across sectors
    may legitimately hold multiple codes. Only use codes from the provided list.
    Each code MUST include a 'reasoning' field explaining why it applies to this entity.
6.  PREDICATE OFFENCE: Always identify the underlying criminal conduct that
    generated the proceeds being laundered, where this can be determined.
7.  KEY FINDINGS: Produce 4–8 discrete, citable legal propositions — not headings.
    Each finding must stand alone as a complete statement of law or fact.
8.  KEY FACTS PER DEFENDANT: Provide 3–6 specific, evidential facts per individual.
    Reference actual figures, company names, dates, transaction amounts, jurisdictions.
9.  POCA ANALYSIS: Map every cited section to the specific facts that engaged it.
    Explain the court's ruling on each provision and any precedent established.
10. PRECEDENT VALUE: State the specific proposition of law this case establishes
    and in what future contexts it would be cited."""

# ── Helpers ────────────────────────────────────────────────────────────────────

def calculate_api_cost(usage_metadata, model_name="gemini-3.5-flash") -> float:
    """
    Calculates the estimated monetary cost of a successful API call 
    based on Pay-As-You-Go pricing per 1 Million tokens.
    """
    # Pricing rates per 1,000,000 tokens
    PRICING_TIERS = {
        "gemini-3.5-flash": {"input": 0.75, "output": 4.50},
        "gemini-3.1-flash-lite": {"input": 0.125, "output": 0.75},
        "gemini-3.1-pro-preview": {"input": 1.00, "output": 6.00},
    }

    if not usage_metadata or model_name not in PRICING_TIERS:
        return 0.0

    # Extract token metrics
    input_tokens = usage_metadata.prompt_token_count or 0
    output_tokens = usage_metadata.candidates_token_count or 0

    # Calculate individual costs
    input_cost = (input_tokens / 1_000_000) * PRICING_TIERS[model_name]["input"]
    output_cost = (output_tokens / 1_000_000) * PRICING_TIERS[model_name]["output"]

    return input_cost + output_cost

def pretty_print_api_error(e: Exception):
    """
    Safely dissects the Google GenAI SDK exception object or raw error text,
    cleaning up any scrambled structures for readable layout.
    """
    try:
        err_msg = ""
        
        # 1. Try to extract structured response data if the SDK attached an HTTP response
        if hasattr(e, 'response') and e.response is not None:
            try:
                # If it's an httpx or requests response object
                if hasattr(e.response, 'json'):
                    data = e.response.json()
                    clean_json = json.dumps(data, indent=4)
                    for line in clean_json.split('\n'):
                        tqdm.write(f"    {line}")
                    return
            except Exception:
                pass

        # 2. Extract error message string (handling specific attribute fallbacks)
        if hasattr(e, 'message') and e.message:
            err_msg = str(e.message)
        else:
            err_msg = str(e)

        # 3. Handle string cleaning if it dumped a stringified dictionary
        start_idx = err_msg.find('{')
        if start_idx != -1:
            dict_part = err_msg[start_idx:]
            # Replace common issues where string mappings have non-strict JSON formatting
            data = ast.literal_eval(dict_part)
            clean_json = json.dumps(data, indent=4)
            
            prefix = err_msg[:start_idx].strip()
            if prefix:
                tqdm.write(f"  Status Detail: {prefix}")
                
            for line in clean_json.split('\n'):
                tqdm.write(f"    {line}")
        else:
            tqdm.write(f"  Raw Error Message: {err_msg}")
            
    except Exception:
        # Emergency absolute fallback: prints whatever text string exists
        tqdm.write(f"  Raw Fallback: {str(e)}")
        
def format_size(b: int) -> str:
    """Human-readable file size for StageTracker's per-case header."""
    if b < 1024:
        return f"{b}B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f}KB"
    return f"{b / (1024 * 1024):.1f}MB"


def estimate_duration(b: int) -> str:
    """
    Rough wall-clock estimate shown in StageTracker's header, bucketed by
    file size. These bands are empirical (observed run times for judgments
    of roughly this size), not derived from any pricing/token model — purely
    to set user expectations while a case is processing.
    """
    kb = b / 1024
    if kb <= 200:  return "~30–45s"
    if kb <= 500:  return "~60–90s"
    if kb <= 1024: return "~90–150s"
    return "~150–240s"


def fmt_time(seconds: float) -> str:
    """Formats a duration in seconds as MM:SS for StageTracker.complete()."""
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


# ── Web Download Helpers ───────────────────────────────────────────────────────

def resolve_xml_url(url: str) -> str:
    """
    Turns a National Archives case-law page URL into its machine-readable
    XML endpoint. Caselaw pages serve human-readable HTML at the base URL
    and the actual Akoma Ntoso XML at "<url>/data.xml" — URLs that already
    point straight at an .xml file are passed through unchanged.
    """
    url = url.strip().rstrip("?")
    if url.endswith(".xml"):
        return url
    if NATIONAL_ARCHIVES_HOST in url:
        return url.rstrip("/") + "/data.xml"
    return url


def _safe_xml_name(title: str) -> str:
    """Strips filesystem-illegal characters from a case title so it can be used as a filename."""
    safe = re.sub(r'[\\/*?"<>|]', '', title)
    safe = re.sub(r' +', ' ', safe).strip()
    return f"{safe[:150]}.xml"


def derive_filename(url: str) -> str:
    """
    Picks a human-readable filename for a downloaded judgment by re-fetching
    the (HTML) case page and scraping its <h1> title and neutral citation —
    e.g. "Shah v HSBC-[2012] EWHC 1283.xml" — since the XML endpoint itself
    carries no such metadata in its URL. Falls back to a sanitised version of
    the URL path itself if the page can't be fetched or parsed.
    """
    try:
        response = requests.get(
            url.strip().rstrip("?"),
            headers=DOWNLOAD_HEADERS,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        html = response.text

        case_name = ""
        h1_match = re.search(r'<h1[^>]*>\s*(.*?)\s*</h1>', html, re.DOTALL)
        if h1_match:
            case_name = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()

        citation = ""
        cite_match = re.search(
            r'\[(\d{4})\]\s+([A-Z]+(?:\s+[A-Z]+)*)\s+(\d+)(?:\s+\(([^)]+)\))?',
            html
        )
        if cite_match:
            citation = cite_match.group(0).strip()

        if case_name and citation:
            return _safe_xml_name(f"{case_name}-{citation}")
        elif case_name:
            return _safe_xml_name(case_name)

    except Exception:
        pass

    path = re.sub(r"https?://[^/]+", "", url)
    path = re.sub(r"/data\.xml$", "", path)
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_")
    return f"{safe}.xml"


def download_xml(url: str, dest: Path) -> bool:
    """Streams the resolved XML URL to dest; returns False on any request failure rather than raising."""
    xml_url = resolve_xml_url(url)
    tqdm.write(f"  Downloading: {xml_url}")
    try:
        response = requests.get(
            xml_url,
            headers=DOWNLOAD_HEADERS,
            timeout=REQUEST_TIMEOUT,
            stream=True
        )
        response.raise_for_status()

        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        tqdm.write(f"  ✓ Saved: {dest.name} ({format_size(dest.stat().st_size)})")
        return True
    except Exception as e:
        tqdm.write(f"  ✗ Download failed: {e}")
        return False


# ── Token / context guard ──────────────────────────────────────────────────────

MAX_CHARS  = 950_000   # Hard stop just under Gemini 3.5 Flash's 1M limit
WARN_CHARS = 800_000   # warn early before hitting the limit


def check_token_length(text: str, filename: str) -> str:
    """
    Guards against exceeding Gemini 3.5 Flash's 1M-token context window.
    Truncates the judgment body (keeping the head, dropping the tail) if it
    would exceed MAX_CHARS, logging the risk so a partial-document analysis
    is visible rather than silent; just warns, without truncating, above
    WARN_CHARS. char-to-token is a rough /4 estimate for the log line only —
    the real enforcement is the character-count guard rail itself.
    """
    char_count = len(text)
    token_est  = char_count // 4

    if char_count > MAX_CHARS:
        tqdm.write(f"  ⚠  Document truncated")
        tqdm.write(f"     File     : {filename}")
        tqdm.write(f"     Extracted: {char_count:,} chars (~{token_est:,} tokens estimated)")
        tqdm.write(f"     Truncated: {MAX_CHARS:,} chars — tail of document removed")
        tqdm.write(f"     Risk     : Analysis based on partial document")
        return text[:MAX_CHARS]

    if char_count > WARN_CHARS:
        tqdm.write(f"  ⚠  Large document warning")
        tqdm.write(f"     File     : {filename}")
        tqdm.write(f"     Extracted: {char_count:,} chars (~{token_est:,} tokens estimated)")
        tqdm.write(f"     Status   : Within limit but large")

    return text


def sanitize_filename(case_ref: str) -> str:
    s = re.sub(r'[\\/*?:"<>|]', '', case_ref)
    s = s.replace('[', '').replace(']', '').replace('(', '').replace(')', '')
    s = re.sub(r'\s+', '_', s.strip())
    return s[:120]


def _send_with_retry(chat, message, label: str, file_path: str, max_retries: int = 2):
    """
    Sends a message on an EXISTING chat object, retrying locally on transient
    failures (429/503/network) without losing the conversation history.

    Why this matters: the outer batch-level 429/503 handler retries by calling
    run_pipeline() again from scratch, which creates a BRAND NEW chat object —
    discarding every tool call already completed in this conversation (e.g. if
    extract_case_metadata and extract_defendants already succeeded and the
    failure happened on classify_sic_codes at iteration 4, a full restart means
    redoing the entire judgment analysis from zero). Retrying on the SAME chat
    object here preserves all prior successful turns; only the one failed
    message needs to be resent.

    Still re-raises after exhausting retries, so the outer handler remains as
    the last-resort fallback for a sustained outage rather than a transient blip.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return _run_with_spinner(label, lambda: chat.send_message(message))
        except Exception as e:
            last_error = e
            err = str(e)
            if attempt < max_retries:
                wait = 60 if ("429" in err or "503" in err) else 5
                tqdm.write(f"\n  ⚠  {label} failed (attempt {attempt + 1}/{max_retries + 1}): {err[:150]}")
                tqdm.write(f"     File : {file_path}")
                tqdm.write(f"     Retrying on the SAME conversation in {wait}s — no progress lost...")
                time.sleep(wait)
            else:
                if "503" in err:
                    tqdm.write(f"  ⚠  503 — Gemini service unavailable ({label}, all local retries exhausted)")
                    tqdm.write(f"     File : {file_path}")
                    tqdm.write("     Tip  : API is overloaded — falling back to a full pipeline retry")
    raise last_error


def _run_with_spinner(label: str, fn):
    """Run fn() while displaying a live elapsed time spinner in the terminal."""
    stop_event = threading.Event()
    start      = time.time()

    def _spin():
        while not stop_event.is_set():
            elapsed = time.time() - start
            tqdm.write(f"\r  ⟳  {label} {elapsed:.1f}s   ", end="")
            time.sleep(0.5)

    thread = threading.Thread(target=_spin, daemon=True)
    thread.start()
    try:
        return fn()
    finally:
        stop_event.set()
        thread.join()
        tqdm.write("")


# ── Stage tracker ──────────────────────────────────────────────────────────────

TOOL_TO_STAGE = {
    "extract_case_metadata": "Analysing case metadata",
    "extract_defendants":    "Extracting defendants",
    "classify_sic_codes":    "Classifying SIC codes",
}

TOTAL_STAGES = 5


class StageTracker:
    """
    Prints a live per-case progress readout to the console: a header when a
    case starts, one line per completed stage (XML read, each tool call,
    output build), and a final summary or failure line. One instance is
    created per case by batch_process()/run_pipeline() — not reused across
    cases — so run_start/current always reflect just the case in flight.
    """

    def __init__(self, filename: str, filesize: int):
        self.filename    = filename
        self.filesize    = filesize
        self.current     = 0
        self.run_start   = time.time()
        self.stage_start = time.time()
        self._header()

    def _header(self):
        bar = "━" * 54
        tqdm.write(f"\n{bar}")
        tqdm.write(f"  {self.filename}")
        tqdm.write(
            f"  Size: {format_size(self.filesize)}"
            f"  |  Estimate: {estimate_duration(self.filesize)}"
            f"  |  Started: {datetime.now().strftime('%H:%M:%S')}"
        )
        tqdm.write(bar)

    def _tick(self, label: str):
        elapsed = time.time() - self.stage_start
        self.current += 1
        tqdm.write(f"  [{self.current}/{TOTAL_STAGES}] {label:<32} ✓  {elapsed:.1f}s")
        self.stage_start = time.time()

    def reading_file(self):
        self._tick("Reading XML")

    def tool_complete(self, tool_name: str):
        self._tick(TOOL_TO_STAGE.get(tool_name, tool_name))

    def building_output(self):
        self._tick("Building output")

    def complete(self, result: dict):
        total  = time.time() - self.run_start
        status = result.get("aml_status", "—")
        count  = result.get("defendant_count", 0)
        tqdm.write("━" * 54)
        tqdm.write(
            f"  ✓ Complete"
            f"  |  Total: {fmt_time(total)} ({total:.1f}s)"
            f"  |  {status}"
            f"  |  {count} defendant(s)"
        )

    def failed(self, reason: str):
        tqdm.write("━" * 54)
        tqdm.write(f"  ✗ Failed: {reason}")

# ── Missing POCA Retrieval ───────────────────────────────────────────────────────
def _section_context_snippets(body_text: str, sections: list, window: int = 350) -> dict:
    """
    Pulls the text surrounding each section's first mention in body_text,
    so the fetch call can ground its answer in the actual judgment rather
    than relying purely on the model's memory of the Act.
    Returns {section_key: snippet}; sections with no match get "" (the
    prompt is told to flag these explicitly rather than guess).
    """
    snippets = {}
    for sec in sections:
        # sec is like 's304' or 's241(1)' — search loosely for "304" / "241"
        num_match = re.match(r's(\d+[A-Z]?)', sec)
        if not num_match:
            snippets[sec] = ""
            continue
        num = num_match.group(1)
        pattern = re.compile(rf'(?:section|s\.?)\s*{re.escape(num)}\b', re.IGNORECASE)
        m = pattern.search(body_text)
        if m:
            start = max(0, m.start() - window)
            end   = min(len(body_text), m.end() + window)
            snippets[sec] = body_text[start:end].strip()
        else:
            snippets[sec] = ""
    return snippets


def fetch_missing_poca_sections(missing_sections: list, body_text: str = "") -> list:
    """
    Calls Gemini to generate structured statutory data for missing POCA sections.

    Grounded in two ways to reduce hallucination risk (previously this was a
    blind 'what does s304 say' call with no source text and an older model,
    which produced confidently wrong content for s304/s305/s307 — it
    described cash/bank-account forfeiture, which is Part 5 Chapter 3, not
    the actual recoverable-property/tracing/accruing-profits content of
    Chapter 2):
      1. Real surrounding text from this judgment, where available.
      2. Same model as the main extraction chat (gemini-3.5-flash), since
         the smaller/older model is a plausible contributor to the error.
    """
    tqdm.write(f"  🔍 Fetching missing POCA reference data: {missing_sections}")

    snippets = _section_context_snippets(body_text, missing_sections) if body_text else {}

    context_block_parts = []
    for sec in missing_sections:
        snippet = snippets.get(sec, "")
        if snippet:
            context_block_parts.append(f"--- {sec} (as it appears in this judgment) ---\n{snippet}")
        else:
            context_block_parts.append(f"--- {sec} ---\n(No surrounding text found in this judgment — rely on the Act itself.)")
    context_block = "\n\n".join(context_block_parts)

    prompt = f"""
    You are a legal data engineer producing reference data for the UK Proceeds of Crime Act 2002 (POCA).

    Provide structured data for these sections: {missing_sections}

    Below is the actual text from a UK judgment showing how each section is used in context.
    Use this to confirm which provision is being referred to before answering — do not rely
    on memory alone if the snippet clarifies the subject matter.

    {context_block}

    For each section, provide:
    1. "section_key" — exact match to the input string, e.g. 's327' or 's241(1)'.
    2. "part_chapter" — the Part and Chapter of POCA 2002 this section sits in
       (e.g. "Part 5, Chapter 2 — Civil Recovery"). State this explicitly so it can be
       checked against known structure; do not omit it.
    3. "title" — short title.
    4. "full" — a comprehensive 2-3 sentence legal overview, accurate to the real
       statutory text. Do NOT confuse adjacent or similarly-numbered provisions
       (e.g. Part 5 Chapter 2 civil recovery sections vs Chapter 3 cash forfeiture
       sections are different and must not be conflated).
    5. "elements" — list of core operational elements.
    6. "notes" — practical legal insights, penalties, or context.
    7. "confidence" — "high" if you are certain this matches the real Act text,
       "low" if you are uncertain or are inferring from general knowledge rather
       than precise recall. If uncertain, say so plainly in "notes" rather than
       presenting a guess as settled fact.
    8. "confidence_reasoning" — a short, specific explanation of WHY you assigned
       that confidence level. For "high": what makes you certain (e.g. clearly
       stated in the provided judgment text, well-established provision you have
       precise recall of). For "low": what exactly is uncertain (e.g. no source
       text was provided for this section, this is easily confused with an
       adjacent provision, you are reconstructing from general structure rather
       than verbatim text). This is for audit purposes — be concrete, not generic.

    Accuracy matters more than completeness — an honest "low confidence, uncertain of
    exact wording" is far more useful than a fluent but wrong answer.
    """

    poca_schema = types.Schema(
        type=types.Type.ARRAY,
        items=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "section_key":  types.Schema(type=types.Type.STRING),
                "part_chapter": types.Schema(type=types.Type.STRING),
                "title":        types.Schema(type=types.Type.STRING),
                "full":         types.Schema(type=types.Type.STRING),
                "elements": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING)
                ),
                "notes":                types.Schema(type=types.Type.STRING),
                "confidence":           types.Schema(type=types.Type.STRING),
                "confidence_reasoning": types.Schema(type=types.Type.STRING),
            },
            required=["section_key", "part_chapter", "title", "full", "elements", "notes", "confidence", "confidence_reasoning"]
        )
    )

    # Completely independent call from the main chat session — but now uses
    # the same model as the main extraction chat, and temperature 0 since
    # this is a factual-recall task with no benefit from variance.
    # ── Local Retry Loop for POCA Fetch ─────────────────────────────────────────
    max_retries = 2
    last_error = None
    response = None
    
    for attempt in range(max_retries + 1):
        try:
            tracker.record_call()
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=poca_schema,
                    temperature=0,
                ),
            )
            break  # Break out of the loop on success
            
        except Exception as e:
            last_error = e
            err = str(e)
            if attempt < max_retries:
                wait = 60 if ("429" in err or "503" in err) else 5
                tqdm.write(f"\n  ⚠  POCA fetch failed (attempt {attempt + 1}/{max_retries + 1}): {err[:150]}")
                tqdm.write(f"     Retrying POCA fetch locally in {wait}s...")
                time.sleep(wait)
            else:
                # If it fails all local retries, raise it to trigger the master file restart
                raise last_error
    # ──────────────────────────────────────────────────────────────────────────

    # ── 💰 Token usage & cost — was previously untracked, off the books ──────
    if response and hasattr(response, 'usage_metadata') and response.usage_metadata:
        cost = calculate_api_cost(response.usage_metadata, "gemini-3.5-flash")
        tracker.record_cost(cost)
        tqdm.write(f"    [POCA fetch] Tokens -> Input: {response.usage_metadata.prompt_token_count} | Output: {response.usage_metadata.candidates_token_count}")
        tqdm.write(f"    [POCA fetch] Estimated Cost: ${cost:.5f}")

    try:
        results = json.loads(response.text)
        for r in results:
            if r.get("confidence") == "low":
                tqdm.write(f"  ⚠ Low-confidence POCA data for {r.get('section_key')} — {r.get('confidence_reasoning', 'no reasoning given')[:150]}")
        return results
    except Exception as e:
        tqdm.write(f"  ⚠ LLM did not return valid JSON for POCA sections. Error: {e}")
        return []

def update_poca_reference(new_items: list):
    """Updates the in-memory dict and saves it cleanly to poca_reference.json."""
    if not new_items:
        return

    # 1. Update the in-memory dictionary
    for item in new_items:
        key = item.get("section_key")
        if key:
            POCA_SECTIONS[key] = {
                "title": item.get("title", ""),
                "full": item.get("full", ""),
                "elements": item.get("elements", []),
                "notes": item.get("notes", ""),
                "part_chapter": item.get("part_chapter", ""),
                "confidence": item.get("confidence", ""),
                "confidence_reasoning": item.get("confidence_reasoning", "")
            }
            
    # 2. Safely dump the entire updated dictionary back to disk
    save_poca_definitions(POCA_SECTIONS)

    tqdm.write(f"  ✓ Added {len(new_items)} new section(s) to poca_reference.json")


# ── Core pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(file_path: str, stage: StageTracker) -> dict:
    """
    Runs the full extraction pipeline for a single XML judgment: parse the
    XML (extractor.py), seed pipeline_state with what was found structurally,
    open a fresh Gemini chat with the system prompt + tool schema, then loop
    sending the model's function calls to execute_tool() and feeding the
    results back until it stops calling tools (or max_iterations is hit).
    Finishes by calling build_output() to assemble the case JSON.

    Called fresh (new chat, new pipeline_state) for every case by
    batch_process() — including on retry, which is why _send_with_retry
    exists to retry within a single call's chat history rather than forcing
    a full run_pipeline restart for every transient failure.
    """
    # Stage 1 — extract XML
    body_text, xml_metadata = extract_from_xml(file_path)
    pipeline_state["body_text"] = body_text
    stage.reading_file()

    # Pre-populate pipeline_state with XML structural metadata
    pipeline_state["xml_metadata"] = xml_metadata

    # Seed case dict with XML-extracted structural fields so the model
    # doesn't waste tokens re-finding facts already structurally known
    pipeline_state["case"] = {
        "case_reference": xml_metadata.get("neutral_citation") or xml_metadata.get("citation"),
        "court":          xml_metadata.get("court"),
        "case_date":      xml_metadata.get("date"),
    }

    # Build context block from XML metadata to orient the model
    xml_context_parts = []
    if xml_metadata.get("citation"):
        xml_context_parts.append(f"Citation        : {xml_metadata['citation']}")
    if xml_metadata.get("court"):
        xml_context_parts.append(f"Court           : {xml_metadata['court']}")
    if xml_metadata.get("date"):
        xml_context_parts.append(f"Date            : {xml_metadata['date']}")
    if xml_metadata.get("judge"):
        xml_context_parts.append(f"Judge           : {xml_metadata['judge']}")
    if xml_metadata.get("docket_number"):
        xml_context_parts.append(f"Docket          : {xml_metadata['docket_number']}")
    if xml_metadata.get("parties"):
        xml_context_parts.append(f"Parties         : {', '.join(xml_metadata['parties'])}")
    if xml_metadata.get("poca_sections"):
        xml_context_parts.append(
            f"POCA sections   : {', '.join(xml_metadata['poca_sections'])} "
            f"(pre-extracted — confirm and add any missed sections from body text)"
        )
    if xml_metadata.get("cited_cases"):
        refs = [c["text"] for c in xml_metadata["cited_cases"][:10]]
        xml_context_parts.append(f"Cases cited     : {', '.join(refs)}")

    xml_context = "\n".join(xml_context_parts)

    body_text = check_token_length(body_text, Path(file_path).name)

    # NOTE: this `config` (with temperature=0.0) is never used — it's
    # superseded by the second `config` assignment below (without
    # temperature, so the model default applies) before any call reads it.
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[tools],
        temperature=0.0
    )

# ── Token Count Guard ─────────────────────────────────────────────────────
    # Pre-flight check: measure the true prompt footprint (system prompt +
    # judgment body) via the API's own tokenizer, since check_token_length()
    # above only estimates from character count. Aborts the case rather than
    # letting an oversized request fail server-side mid-call.
    text_to_measure = SYSTEM_PROMPT + "\n" + body_text

    try:
        token_count_resp = client.models.count_tokens(
            model="gemini-3.5-flash",
            contents=text_to_measure
        )
        total_tokens = token_count_resp.total_tokens
        tqdm.write(f"  📊 Total Context Footprint: {total_tokens:,} tokens")

        if total_tokens > 950_000:
            tqdm.write(f"  ❌ File skipped: {total_tokens:,} tokens exceeds safety threshold.")
            return {"error": f"Context size ({total_tokens} tokens) is too large."}

    except Exception as e:
        tqdm.write(f"  ⚠ Token counter failed to execute: {e}")
    # ──────────────────────────────────────────────────────────────────────────

    # Actual config used for the chat session (see NOTE above re: the earlier one)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[tools]
    )

# ── Model Configuration ─────────────────────────────────────────────────────
    chat = client.chats.create(model="gemini-3.5-flash", config=config)

    # ── Initial extraction call ────────────────────────────────────────────────
    tracker.record_call()

    initial_message = (
        f"Analyse this UK legal judgment for AML intelligence.\n\n"
        f"You must call all three tools:\n"
        f"  1. extract_case_metadata — populate every field fully. "
        f"     key_findings must contain 4–8 complete, citable legal propositions. "
        f"     poca_analysis must map every cited section to specific facts and the court's ruling. "
        f"     precedent_value must state what proposition of law this case establishes.\n"
        f"  2. extract_defendants — list every party exactly once. "
        f"     key_facts must contain 3–6 specific evidential facts per individual "
        f"     (amounts, dates, companies, transactions). "
        f"     poca_section_reasoning must map facts to statutory elements, not restate the section title.\n"
        f"  3. classify_sic_codes — for every defendant, assign all applicable codes. "
        f"     Each code must include a 'reasoning' field citing specific case evidence.\n\n"
        f"PRE-EXTRACTED FROM XML — use as ground truth for structural fields:\n"
        f"{xml_context}\n\n"
        f"AVAILABLE SIC CODES — only assign from this list:\n"
        f"{SIC_PROMPT_BLOCK}\n\n"
        f"JUDGMENT TEXT:\n{body_text}"
    )

    response = _send_with_retry(chat, initial_message, "Waiting for Gemini...", file_path)

    iteration      = 0
    max_iterations = 15

    while iteration < max_iterations:
        iteration += 1

        function_calls = [
            part.function_call
            for part in response.candidates[0].content.parts
            if part.function_call
        ]

        if not function_calls:
            break

        tool_responses = []
        for call in function_calls:
            result = execute_tool(call.name, dict(call.args))
            stage.tool_complete(call.name)
            tool_responses.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=call.name,
                        response=json.loads(result)
                    )
                )
            )

        tracker.record_call()
        response = _send_with_retry(
            chat, tool_responses,
            f"Processing tool response (iteration {iteration})...",
            file_path
        )

    # ── 💰 Print Token Usage & Cost  ──────────
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        cost = calculate_api_cost(response.usage_metadata, "gemini-3.5-flash")
        tracker.record_cost(cost)
        tqdm.write(f"  ✔ Gemini chat complete!")
        tqdm.write(f"    Tokens Used -> Input: {response.usage_metadata.prompt_token_count} | Output: {response.usage_metadata.candidates_token_count}")
        tqdm.write(f"    Estimated Cost: ${cost:.5f}")

    # Final stage — build output (POCA enrichment happens inside build_output)
    stage.building_output()
    return build_output()

# ── Save helper ────────────────────────────────────────────────────────────────

def _save_result(output: dict, output_dir: Path, file: Path) -> None:
    """Writes one case's output JSON, named after its case_reference (falling back to the source filename if the model didn't return one)."""
    case_ref = output.get("case_reference") or sanitize_filename(file.stem)
    filename = output_dir / f"{sanitize_filename(case_ref)}.json"
    with open(filename, "w") as f:
        json.dump(output, f, indent=2)
    tqdm.write(f"  → Saved: {filename.name}")


# ── Batch processor ────────────────────────────────────────────────────────────

def batch_process(folder: str) -> list:
    """
    Runs run_pipeline() over every .xml file in folder, handling failures
    with a tiered retry cascade:
      - 429 (rate limit): tracker.handle_429() computes a cooldown from the
        error's retryDelay, then one full retry.
      - 503 (service unavailable): up to 3 retries with a fixed exponential
        backoff (90s/180s/270s).
      - anything else: logged as a failure for this file, batch continues.

    Each attempt (initial + every retry) repeats the same POCA-enrichment
    check and output-folder-grouping steps, since a successful retry is a
    brand-new run_pipeline() call producing a brand-new `output` dict that
    still needs the same post-processing as the first attempt. That
    duplication (identical logic inlined 3x below) is a known wart, not an
    intentional pattern — the retry/backoff branches were extended
    incrementally rather than factored into a helper.

    Returns (results, successes, failures): results is a list of case dicts
    (or {"source_file", "error"} for failed files), for the caller to
    print a summary and for each success to have already been written to
    outputs/.
    """
    files = sorted(Path(folder).glob("*.xml"))
    if not files:
        print(f"No XML files found in {folder}")
        return [], 0, 0

    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    results   = []
    successes = 0
    failures  = 0

    with tqdm(
        files,
        desc="Batch Progress",
        unit="file",
        colour="green",
        position=0,
        leave=True
    ) as batch_bar:

        for file in batch_bar:
            batch_bar.set_postfix_str(file.name[:30])
            pipeline_state.clear()
            stage = StageTracker(file.name, file.stat().st_size)

            try:
                output = run_pipeline(str(file), stage)

                # POCA reference gap-fill: build_output() enriched the cited
                # sections against POCA_SECTIONS as it stood before this
                # case ran; any section this case cites that isn't in that
                # dict yet gets fetched now and the enrichment redone so the
                # saved output isn't left with a placeholder entry.
                identified_sections = output.get("poca_sections", [])
                missing_in_this_case = []

                for section in identified_sections:
                    if not section or section == "N/A":
                        continue
                    clean_sec = section.strip()
                    if clean_sec not in POCA_SECTIONS:
                        missing_in_this_case.append(clean_sec)

                if missing_in_this_case:
                    new_poca_data = fetch_missing_poca_sections(list(set(missing_in_this_case)), body_text=pipeline_state.get("body_text", ""))
                    update_poca_reference(new_poca_data)
                    output["poca_sections_enriched"] = _enrich_poca_sections(identified_sections)

                output["source_file"] = file.name
                results.append(output)
                stage.complete(output)

                # Group the case's JSON output and its source XML together
                # under outputs/<case name>/ rather than a flat outputs/ dir,
                # named after the XML filename (stripped of a literal
                # "&amp;" left over from the XML's escaped ampersands).
                folder_name = file.stem.replace("&amp;", "&").replace("amp;", "").strip()
                case_folder = output_dir / folder_name
                case_folder.mkdir(parents=True, exist_ok=True)

                _save_result(output, case_folder, file)
                successes += 1

                shutil.move(str(file), str(case_folder / file.name))
                tqdm.write(f"  → Grouped JSON and XML in: {case_folder}/")

            except Exception as e:
                err = str(e)

                # ── Pretty Print the API Error directly to console ──────────
                tqdm.write("\n  ⚠️  API Error Encountered:")
                pretty_print_api_error(e)  # <-- PASS THE ACTUAL EXCEPTION OBJECT 'e' HERE
                tqdm.write("━" * 54)

                # ── 429 rate limit — countdown then retry ──────────────────
                if "429" in err:
                    wait = tracker.handle_429(err) + 10  # add buffer to ensure limit has reset
                    tqdm.write(f"  ⚠  429 Rate limit hit — waiting {wait}s before retrying...")
                    for _ in tqdm(
                        range(wait, 0, -1),
                        desc="  Rate limit cooldown",
                        unit="s",
                        leave=False,
                        position=1
                    ):
                        time.sleep(1)

                    try:
                        # Retry of the same file after the 429 cooldown above — repeats
                        # the same POCA gap-fill and folder-grouping steps as the first
                        # attempt (see the comments on that path above) since this is a
                        # fresh run_pipeline() call producing a fresh `output`.
                        pipeline_state.clear()
                        stage2 = StageTracker(file.name, file.stat().st_size)
                        output = run_pipeline(str(file), stage2)
                        identified_sections = output.get("poca_sections", [])
                        missing_in_this_case = []

                        for section in identified_sections:
                            if not section or section == "N/A":
                                continue
                            clean_sec = section.strip()
                            if clean_sec not in POCA_SECTIONS:
                                missing_in_this_case.append(clean_sec)

                        if missing_in_this_case:
                            new_poca_data = fetch_missing_poca_sections(list(set(missing_in_this_case)), body_text=pipeline_state.get("body_text", ""))
                            update_poca_reference(new_poca_data)
                            output["poca_sections_enriched"] = _enrich_poca_sections(identified_sections)

                        output["source_file"] = file.name
                        results.append(output)
                        stage2.complete(output)

                        folder_name = file.stem.replace("&amp;", "&").replace("amp:", "").strip()
                        case_folder = output_dir / folder_name
                        case_folder.mkdir(parents=True, exist_ok=True)

                        _save_result(output, case_folder, file)
                        successes += 1
                        shutil.move(str(file), str(case_folder / file.name))
                        tqdm.write(f"  → Grouped JSON and XML in: {case_folder}/")

                    except Exception as e2:
                        stage.failed(str(e2))
                        results.append({"source_file": file.name, "error": str(e2)})
                        failures += 1

                # ── 503 service unavailable — exponential backoff, 3 retries ──
                elif "503" in err:
                    retry_waits   = [90, 180, 270]
                    retry_success = False

                    for attempt, wait in enumerate(retry_waits, start=1):
                        tqdm.write(f"  ↻  503 retry {attempt}/3 — waiting {wait}s...")
                        for _ in tqdm(
                            range(wait, 0, -1),
                            desc=f"  503 cooldown (attempt {attempt})",
                            unit="s",
                            leave=False,
                            position=1
                        ):
                            time.sleep(1)

                        try:
                            # Retry of the same file after a 503 backoff wait — same
                            # POCA gap-fill / folder-grouping steps as the first attempt
                            # above, since this is another fresh run_pipeline() call.
                            pipeline_state.clear()
                            stage2 = StageTracker(file.name, file.stat().st_size)
                            tqdm.write(f"  ↻  Retrying {file.name} (attempt {attempt}/3)...")
                            output = run_pipeline(str(file), stage2)
                            identified_sections = output.get("poca_sections", [])
                            missing_in_this_case = []

                            for section in identified_sections:
                                if not section or section == "N/A":
                                    continue
                                clean_sec = section.strip()
                                if clean_sec not in POCA_SECTIONS:
                                    missing_in_this_case.append(clean_sec)

                            if missing_in_this_case:
                                new_poca_data = fetch_missing_poca_sections(list(set(missing_in_this_case)), body_text=pipeline_state.get("body_text", ""))
                                update_poca_reference(new_poca_data)
                                output["poca_sections_enriched"] = _enrich_poca_sections(identified_sections)

                            output["source_file"] = file.name
                            results.append(output)
                            stage2.complete(output)

                            folder_name = file.stem.replace("&amp;", "&").replace("amp:", "").strip()
                            case_folder = output_dir / folder_name
                            case_folder.mkdir(parents=True, exist_ok=True)

                            _save_result(output, case_folder, file)
                            successes += 1

                            shutil.move(str(file), str(case_folder / file.name))
                            tqdm.write(f"  → Grouped JSON and XML in: {case_folder}/")
                            retry_success = True
                            break
                        except Exception as retry_err:
                            retry_str = str(retry_err)
                            if "503" in retry_str:
                                tqdm.write(f"  ✗  Attempt {attempt}/3 failed — still unavailable")
                                if attempt == len(retry_waits):
                                    stage.failed(f"503 after {len(retry_waits)} retries: {retry_str}")
                                    results.append({"source_file": file.name, "error": retry_str})
                                    failures += 1
                            else:
                                stage.failed(retry_str)
                                results.append({"source_file": file.name, "error": retry_str})
                                failures += 1
                                break

                    # NOTE: this branch is a no-op (`pass`) — by this point `err`
                    # was already established to contain "503" (it's the condition
                    # that routed execution into this `elif` in the first place),
                    # so `"503" not in str(err)` can never be true here.
                    if not retry_success and "503" not in str(err):
                        pass

                # ── Any other error — log and move on ─────────────────────
                else:
                    stage.failed(err)
                    results.append({"source_file": file.name, "error": err})
                    failures += 1

    return results, successes, failures


if __name__ == "__main__":
    print(f"\n{'━' * 54}")
    print("  Initializing Pipeline...")

    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    CASES_DIR.mkdir(parents=True, exist_ok=True)


    # Two ways to populate CASES_DIR (the folder batch_process actually reads):
    # either download the judgment(s) at the URL(s) passed as CLI args, or —
    # with no args — pull the smallest already-downloaded file waiting in
    # ACTIVE_DIR. Smallest-first is a deliberate throttle for manual batches:
    # it lets you sanity-check the pipeline on a cheap/fast case before
    # committing API spend to the larger files sitting alongside it.
    urls = sys.argv[1:]

    if urls:
        print(f"  Found {len(urls)} URL(s) provided via command line.")
        for url in urls:
            filename  = derive_filename(url)
            dest_path = CASES_DIR / filename
            download_xml(url, dest_path)

    else:
        active_xmls = list(ACTIVE_DIR.glob("*.xml"))
        if active_xmls:
            smallest_xml = min(active_xmls, key=lambda p: p.stat().st_size)
            target_path  = CASES_DIR / smallest_xml.name
            print(f"  Found {len(active_xmls)} file(s) in Active Storage.")
            print(f"  Selected smallest: {smallest_xml.name} ({format_size(smallest_xml.stat().st_size)})")
            shutil.move(str(smallest_xml), str(target_path))
            print(f"  Moved to cases/ for processing.")
        else:
            print(f"  No XML files found in Active Storage.")

    all_results, successes, failures = batch_process(str(CASES_DIR))

    print(f"\n{'━' * 54}")
    print(f"  Batch complete")
    print(f"  Processed : {len(all_results)} file(s)")
    print(f"  Succeeded : {successes}")
    print(f"  Failed    : {failures}")
    if successes:
        print(f"  JSONs written to outputs/")
        print(f"  Successfully processed XMLs moved to outputs/")
    tracker.display()
