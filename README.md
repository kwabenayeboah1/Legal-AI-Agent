# Legal AML Intelligence Pipeline: A Technical Write-Up
<img width="909" height="360" alt="360_F_483867498_t6tSA4UQx2VspTFAIn4mA8NF8I00Uyce" src="https://github.com/user-attachments/assets/22a82161-bbf1-4146-a6af-036b9142b030" />

**Author:** Kwabena Yeboah (Bena)  
**Stack:** Python · Gemini API · AkomaNtoso XML · Streamlit  
**Status:** Proof of Concept — Sample size insufficient for evidenced conclusions  
**Last Updated:** 25/06/2026

---

## Table of Contents

1. [Background & Hypothesis](#1-background--hypothesis)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [From App to Agent — Why the Pipeline Evolved](#3-from-app-to-agent--why-the-pipeline-evolved)
4. [Data Ingestion — XML via AkomaNtoso](#4-data-ingestion--xml-via-akomanntoso)
5. [Module Breakdown](#5-module-breakdown)
6. [SIC Code Classification](#6-sic-code-classification)
7. [LLM Reasoning Design — Function Calling & System Instruction](#7-llm-reasoning-design--function-calling--system-instruction)
8. [Tool Design Rationale](#8-tool-design-rationale)
9. [Output Schema](#9-output-schema)
10. [Streamlit Results Viewer](#10-streamlit-results-viewer)
11. [Findings](#11-findings)
12. [A Notable LLM Quirk — The Divergent Verdict Problem](#12-a-notable-llm-quirk--the-divergent-verdict-problem)
13. [Misclassification Taxonomy](#13-misclassification-taxonomy)
14. [Limitations](#14-limitations)
15. [Future Work](#15-future-work)
16. [Appendix](#16-appendix)

---

## 1. Background & Hypothesis

This project originated from a conversation with a colleague and mentor who had been independently researching the relationship between money laundering offences and the legal sector — specifically, whether patterns could be identified linking certain business types (via SIC codes) to Proceeds of Crime Act 2002 (POCA 2002) convictions.

The informal hypothesis was:

> *"Is there a statistically meaningful link between certain business classifications and money laundering convictions in the UK legal system?"*

The challenge: Build a pipeline that could ingest real UK court case documents at scale, apply structured LLM reasoning against a defined legal framework, classify the businesses involved, and surface patterns across a corpus. The system prompt was vetted continuously and trial runs were committed to get the right level of analysis before committing to an initial triage of 100 separate case files.

Two workstreams emerged:

1. **The App** — an interactive, single-case analysis tool built in Google AI Studio. This served as the proof of concept and is the origin of the methodology described in this [document](https://github.com/kwabenayeboah1/AML-Analyser).
2. **The AI Agent** — an automated agentic pipeline (this repo) replicating and extending the App's workflow: automated ingestion, reasoning, classification, and structured output, with no human-in-the-loop required at the case level.

This document covers the Agent pipeline in full technical detail. The App is discussed in Section 3 as context for the architectural decisions made here.

---

## 2. System Architecture Overview

The pipeline is deterministic in structure and agentic in reasoning. Each module has a single, clearly scoped responsibility; the LLM operates within a defined function-calling schema rather than returning free-form text.

```
┌─────────────────────────────────────────────────────────────────┐
│                  National Archives Case Source                  │
│              (AkomaNtoso XML — UK Court Judgments)              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
              ┌─────────────▼──────────────┐
              │        extractor.py        │
              │  XML Parsing & Metadata    │
              │  Case body · Parties ·     │
              │  Court · Date · Sections   │
              └─────────────┬──────────────┘
                            │
              ┌─────────────▼──────────────┐
              │       poca_loader.py       │
              │  Shared POCA 2002 Reference│
              │  s.327 · s.328 · s.329     │
              │  (single source of truth)  │
              └──────┬──────────────┬──────┘
                     │              │
         ┌───────────▼───┐    ┌─────▼──────────────┐
         │   tools.py    │    │     main.py        │
         │Gemini Function│    │    Pipeline        │
         │Calling Schema │    │    Orchestration   │
         │ (structured   │    │  · _send_with_     │
         │  tool defs)   │    │    retry()         │
         └───────────┬───┘    │  · Self-healing    │
                     │        │    POCA fetch      │
                     └────────┤  · Agentic loop    │
                              └─────────┬──────────┘
                                        │
                              ┌─────────▼────────────┐
                              │     executor.py      │
                              │  Pipeline State &    │
                              │  Output Assembly     │
                              │  · Tool result       │
                              │    processing        │
                              │  · JSON construction │
                              └─────────┬────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
        ┌───────────▼──────┐  ┌─────────▼───────┐  ┌────────▼────────┐
        │  Structured JSON │  │  streamlit_app  │  │  Excel Export   │
        │  Output per Case │  │  Results Viewer │  │  (.xlsx)        │
        └──────────────────┘  └─────────────────┘  └─────────────────┘
```

**Key architectural principles:**

- **Single source of truth** — `poca_loader.py` serves POCA 2002 definitions to the entire pipeline. No hardcoded statute text in any other module.
- **Deterministic structure, agentic reasoning** — the pipeline flow is fixed; the LLM's reasoning within that flow is not. Function calling constrains the output shape without constraining the reasoning.
- **Retry and self-healing** — `_send_with_retry()` in `main.py` handles transient Gemini API failures. A self-healing mechanism re-fetches missing POCA section references mid-loop if the model invokes a section not currently in context.
- **Separation of concerns** — extraction, reasoning schema, orchestration, and output assembly are handled by distinct modules. Nothing does two jobs.

---

## 3. From App to Agent — Why the Pipeline Evolved

The App — built in Google AI Studio — proved the hypothesis was worth pursuing. It could ingest a PDF, reason over it, and return a structured verdict. I decided to build an Agent not only to flex my technical muscles, but because I understood a productionised environment would benefit more from autonomous agents. The App served its purpose as a POC of a UI being built, but this Agentic workflow works better in ensuring cases could be ingested in huge batches and left to run. 

Three specific limitations drove the move to an agentic pipeline:

**1. PDF ingestion is fragile at scale.**  
Legal PDFs vary enormously in structure — clean digital exports, scanned documents, multi-column layouts, inconsistent section headers. `pdfplumber` handled most of this, but extraction noise was a recurring problem with older judgments. [National Archives](https://caselaw.nationalarchives.gov.uk/) publishes case law in AkomaNtoso XML — a structured, machine-readable format with clearly delimited sections and embedded metadata. Switching to XML eliminated the extraction noise problem at source. It was also considered that for token efficiency, using XML files would be more efficient than using an LLM call to parse through a PDF file. 

**2. Single-case interactivity doesn't compound.**  
The App produced one JSON output per session. There was no persistent state, no accumulation across cases, no way to query patterns without manually aggregating outputs. An agentic pipeline that writes structured JSON per case and exports to a consistent schema makes the corpus queryable from day one.

**3. Human-in-the-loop is a bottleneck, not a feature.**  
At the App stage, human review was a feature — it allowed rapid iteration on the system instruction and early identification of model failure modes (see Section 11). Once the instruction was validated, human-in-the-loop became unnecessary overhead. The agent removes it.

The App is not deprecated — it remains the fastest way to run a single case interactively. The agent is what runs the corpus.

---

## 4. Data Ingestion — XML via AkomaNtoso

UK court judgments are published by [National Archives](https://caselaw.nationalarchives.gov.uk/) in AkomaNtoso XML format — an open standard for legal documents used across multiple jurisdictions.

### Why AkomaNtoso over PDF

| Dimension | PDF | AkomaNtoso XML |
|---|---|---|
| Structure | Implicit (layout-dependent) | Explicit (tagged sections) |
| Metadata | Embedded inconsistently | First-class elements |
| Extraction reliability | Variable | High |
| Section identification | Heuristic | Deterministic |
| Scale suitability | Low–Medium | High |

The XML structure gives `extractor.py` direct access to case metadata (reference, court, date, parties) and the substantive judgment body without any layout parsing or heuristic section detection.

### Extraction Process

`extractor.py` processes each AkomaNtoso file in the following sequence:

1. **Namespace handling** — AkomaNtoso uses XML namespaces that must be resolved before any element access. `extractor.py` normalises these at parse time.
2. **Metadata extraction** — case reference, court, judgment date, and party names are pulled from designated metadata elements.
3. **Body text extraction** — the substantive judgment text is extracted from the `<body>` element, preserving paragraph structure.
4. **Section tagging** — where AkomaNtoso section markers are present (Facts, Findings, Verdict, Sentence), these are preserved as tags passed downstream, allowing `main.py` to prioritise the most evidentially relevant portions when constructing the model prompt.
5. **Text cleaning** — XML entities are decoded, whitespace is normalised, and any residual markup artifacts are stripped before the text is passed to the LLM.

---

## 5. Module Breakdown

### `main.py` — Orchestration

The entry point and orchestration layer. Responsibilities:

- Accepts a case file path, loads and passes it through `extractor.py`. Can also pass through a web link to the particular case and it will extract the .XML
- Constructs the Gemini API request with the system instruction, extracted case text, and tool definitions from `tools.py`
- Runs the **agentic loop**: sends the request, processes tool calls returned by the model, feeds tool results back into the conversation, and iterates until the model signals completion
- Implements `_send_with_retry()` — exponential backoff with jitter for transient API errors (rate limits, timeouts, 4xx/5xx responses)
- Implements **self-healing POCA fetch** — if the model invokes a POCA section reference not currently in context, `main.py` fetches it from `poca_loader.py` and injects it into the next turn rather than failing
- Passes the completed output to `executor.py` for assembly

### `extractor.py` — XML Parsing

Handles all AkomaNtoso XML ingestion as described in Section 4. Returns a structured dict of case metadata and cleaned body text. Has no knowledge of the LLM or output schema — pure extraction.

### `poca_loader.py` — Shared POCA Reference

Loads and exposes POCA 2002 section definitions as a shared in-memory dict. This module exists specifically to solve a divergence problem encountered during development: without a single source of truth, `main.py`'s self-healing fetch mechanism was updating a definition that `executor.py` was not reading, because each module had instantiated its own copy. `poca_loader.py` ensures the entire pipeline references the same object.

The dict is structured as:

```python
POCA_SECTIONS = {
    "s.327": {
        "title": "Concealing etc.",
        "text": "A person commits an offence if he conceals criminal property..."
    },
    "s.328": {
        "title": "Arrangements",
        "text": "A person commits an offence if he enters into or becomes concerned..."
    },
    "s.329": {
        "title": "Acquisition, use and possession",
        "text": "A person commits an offence if he acquires criminal property..."
    }
}
```

### `tools.py` — Gemini Function Calling Schema

Defines the structured tools the Gemini model can invoke during its reasoning process. This is the architectural difference between the App and the Agent: rather than prompting the model to return structured text, `tools.py` defines the exact output structure as callable functions. The model invokes these as part of its reasoning loop; the pipeline processes the function call results rather than parsing free-form text.

Key tool definitions include:

- **`record_verdict`** — the primary output tool. Accepts verdict, confidence score, POCA sections identified, reasoning chain, and the `aml_referenced_as_precedent` flag.
- **`lookup_poca_section`** — allows the model to request a specific POCA section definition mid-reasoning. This is what the self-healing mechanism in `main.py` responds to.
- **`classify_sic_codes`** — accepts extracted business descriptions and returns matched SIC codes with confidence scores.
- **`raise_flag`** — allows the model to surface anomalies (conflicting charges, incomplete documentation, ambiguous entity structure) without embedding them in the reasoning narrative.

### `executor.py` — Output Assembly

Receives the completed agentic loop output from `main.py` and assembles the final structured JSON object per case. Responsibilities:

- Processes all tool call results from the loop
- Resolves any conflicts between tool outputs (e.g. multiple `raise_flag` calls)
- Constructs the final JSON object against the schema defined in Section 8
- Writes the output to the case log and triggers Excel export

### `streamlit_app.py` — Results Viewer

A lightweight Streamlit front-end for inspecting processed cases without reading raw JSON. Surfaces: case metadata, verdict and confidence score, POCA sections identified, the model's full reasoning chain, matched SIC codes, and any flags raised. Designed for rapid review of individual cases and identification of low-confidence outputs warranting manual inspection.

---

## 6. SIC Code Classification

Standard Industrial Classification (SIC) codes are used by Companies House to categorise business activity. A money laundering conviction in isolation tells you a crime occurred. A conviction *with a SIC code* tells you something about the structural conditions that may have enabled it — and patterns across SIC codes across a corpus tell you something about systemic risk in specific sectors.

### Data Source

Full UK SIC 2007 code list, loaded from `.csv`:

```
code, description
6419, Other monetary intermediation
6820, Renting and operating of own or leased real estate
6920, Accounting, bookkeeping and auditing activities; tax consultancy
...
```

### Multi-SIC Matching Logic

A defendant may operate under multiple SIC codes. A single-code approach would systematically misrepresent businesses with diverse operations — a holding company spanning real estate, financial intermediation, and professional services deserves a more honest representation than a single bucket.

The matching process via `classify_sic_codes`:

1. The model extracts business name(s) and trading descriptions from the case text during its reasoning loop
2. These are passed to the SIC classification tool, which performs fuzzy matching against the `.csv` description field
3. All plausible matches above a defined confidence threshold are returned — not just the top result
4. Each matched code is included in the output with its own confidence score
5. The final output represents the defendant's *industry footprint*, not a forced single classification

This sacrifices simplicity for accuracy — the right trade-off when the purpose is pattern identification across a corpus.

---

## 7. LLM Reasoning Design — Function Calling & System Instruction

### System Instruction Design Principles

The system instruction is not a loose prompt. It is a tightly scoped legal brief handed to the model before any case content is provided. Key principles:

**Role definition** — the model is told it is a legal analysis assistant with a specific and narrow remit: reason over UK court cases and determine whether a POCA 2002 money laundering offence was committed, proven, and convicted.

**Legal framework anchoring** — POCA 2002 is cited directly. Sections s.327, s.328, and s.329 are referenced explicitly to constrain reasoning to the correct statutory framework rather than a general conception of "money laundering." Other relevant sections were added to tighten the logic after initial triage developed my understanding of what was required to streamline results.

**Mandatory reasoning requirement** — the model must explain its reasoning *before* invoking `record_verdict`. This is chain-of-thought by architectural design, not by hope. It also gives the analyst a mechanism to identify reasoning failures without re-reading the full case.

**Explicit scope boundary** — the model is instructed to treat AML appearing as *cited precedent or dropped charge* as categorically distinct from AML as *the basis of conviction*. This boundary is the most important single line in the system instruction. See Section 11.

**Illustrative system instruction structure:**

```
You are a senior financial crime specialist with 20 years of experience across:
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
    and in what future contexts it would be cited.
```

### Function Calling vs. Prompted Output

The App (Google AI Studio) relied on prompting the model to return structured JSON and post-processing the response. The Agent uses Gemini's native function calling. The distinction matters:

| Approach | Structured output | Failure mode |
|---|---|---|
| Prompted JSON | Model attempts to format correctly | Schema drift, missing fields, markdown wrapping |
| Function calling | Model invokes typed tool definitions | Tool invocation failure (catchable and retryable) |

Function calling makes output schema compliance an API-level guarantee rather than a parsing problem.

---

## 8. Tool Design Rationale

Each tool in `tools.py` exists to prevent a specific, observed or anticipated failure mode — not as a generic capability. This section documents the rationale behind each one, because the design decisions are more instructive than the definitions themselves.

### `record_verdict` — Enforcing Outcome Structure

**The failure mode it prevents:** In the App, the model was prompted to return structured JSON. Schema drift was a recurring problem — missing fields, inconsistent verdict labels (`"Convicted"` vs `"CONVICTED"` vs `"Yes"`), confidence scores outside the defined range, reasoning embedded in the wrong field. Every downstream aggregation step had to defensively handle these variations.

**The design response:** `record_verdict` defines the output schema as a typed function signature. The model cannot return a verdict without invoking this tool with the correct field types. Schema compliance becomes an API-level guarantee rather than a parsing problem. The reasoning field is a required parameter — the model cannot skip it and go straight to a verdict.

**What it does not solve:** It cannot force the model to reason *well*, only to reason *visibly*. A confidently wrong verdict with plausible-sounding reasoning will pass schema validation. That is why the confidence score and the analyst review layer both exist.

---

### `lookup_poca_section` — On-Demand Statute Reference

**The failure mode it prevents:** Static context injection of all POCA sections at the start of every request created two problems. First, it consumed a meaningful portion of the context window on every case, regardless of which sections were actually relevant. Second, and more subtly, the model's reasoning quality degraded on longer cases where the statute definitions appeared early and the case facts appeared late — by the time the model reached the verdict, the statutory anchoring had receded in effective attention weight.

**The design response:** `lookup_poca_section` allows the model to fetch a specific section definition *at the point in its reasoning where it is relevant* — immediately before applying the statutory test. This keeps statute text proximate to its application in the reasoning chain, which measurably improves the quality and specificity of the statutory analysis. It also enables the self-healing mechanism in `main.py`: if the model invokes a section not currently loaded, `main.py` fetches it from `poca_loader.py` and injects it into the next turn without failing.

**The non-linear reasoning observation:** This tool only became necessary because the model's reasoning is non-linear. It does not process statutes in a fixed order — it reaches for the section most relevant to the facts as it encounters them. A static injection approach assumes linear reasoning; `lookup_poca_section` accommodates the reality.

---

### `classify_sic_codes` — Decoupling Business Classification from Legal Reasoning

**The failure mode it prevents:** In early iterations, SIC code classification was embedded in the main reasoning prompt. The model was asked to simultaneously reason about the legal outcome *and* classify the business. Two problems emerged. First, the tasks interfered with each other — legal reasoning about financial crime can prime the model to over-associate defendants with certain business types, introducing classification bias. Second, multi-code matching was inconsistent when done in free-form reasoning; the model would sometimes return one code, sometimes three, with no reliable schema.

**The design response:** `classify_sic_codes` separates business classification into a discrete tool invocation with a typed array return — one entry per matched code, each with its own confidence score. Classification happens independently of verdict reasoning. The model cannot embed SIC codes in its reasoning narrative and forget to return them as structured data.

**The bias angle:** Decoupling is also an analytical integrity decision. A model reasoning about whether someone is guilty of financial crime should not be simultaneously classifying their business — the two tasks, run together, risk contaminating each other in ways that are hard to detect and harder to correct.

---

### `raise_flag` — Surfacing Anomalies Without Polluting the Reasoning Chain

**The failure mode it prevents:** Without a structured flag mechanism, the model had two options when it encountered an anomaly — embed it in the reasoning narrative (making it hard to query systematically) or ignore it (losing the signal entirely). Neither is acceptable when the purpose is pattern detection across a corpus.

**The design response:** `raise_flag` gives the model a dedicated channel for anomalies: conflicting charges, incomplete documentation, ambiguous entity structures, cases where the defendant's business cannot be reliably identified, or anything that warrants human review for reasons other than verdict uncertainty. Flags are surfaced separately from the reasoning chain in both the JSON output and the Streamlit viewer — they are queryable as a field, not buried in prose.

**The broader principle:** `raise_flag` encodes a specific philosophy about the analyst relationship. The pipeline is not designed to replace legal judgement — it is designed to direct it efficiently. Flags are the mechanism by which the model communicates the boundary of its own confidence, beyond the confidence score alone.

---

Each processed case produces a structured JSON object. Schema consistency across all cases is what makes downstream analysis tractable.

```json
{
  "case_reference": "string",
  "case_name": "string",
  "court": "string",
  "judgment_date": "YYYY-MM-DD",
  "defendant": {
    "name": "string",
    "business_name": "string",
    "sic_codes": [
      {
        "code": "integer",
        "description": "string",
        "confidence": "float (0.0–1.0)"
      }
    ]
  },
  "aml_analysis": {
    "poca_sections_identified": ["s.327", "s.328", "s.329"],
    "aml_referenced_as_precedent": "boolean",
    "reasoning": "string",
    "verdict": "CONVICTED | NOT_CONVICTED | UNCLEAR",
    "confidence_score": "integer (0–100)"
  },
  "case_summary": "string",
  "flags": ["string"]
}
```

### Key Schema Decisions

- **`aml_referenced_as_precedent`** — Boolean flag for the precedent/conviction distinction (Section 11). Any case where this is `true` and `verdict` is `CONVICTED` warrants manual review — it is the most likely failure mode.
- **`flags`** — free-text array for model-surfaced anomalies via the `raise_flag` tool: conflicting charges, incomplete documentation, ambiguous entity structure.
- **`sic_codes` as an array** — enforces multi-code classification. A single-value field would have been architecturally easier and analytically weaker.
- **`confidence_score` on verdict, not just SIC** — the model expresses uncertainty on the legal verdict as well as the business classification. Both are needed to triage outputs for manual review.

---

## 9. Output Schema

Each processed case produces a structured JSON object. Schema consistency across all cases is what makes downstream analysis tractable.

```json
{
  "case_reference": "string",
  "case_name": "string",
  "court": "string",
  "judgment_date": "YYYY-MM-DD",
  "defendant": {
    "name": "string",
    "business_name": "string",
    "sic_codes": [
      {
        "code": "integer",
        "description": "string",
        "confidence": "float (0.0–1.0)"
      }
    ]
  },
  "aml_analysis": {
    "poca_sections_identified": ["s.327", "s.328", "s.329"],
    "aml_referenced_as_precedent": "boolean",
    "reasoning": "string",
    "verdict": "CONVICTED | NOT_CONVICTED | UNCLEAR",
    "confidence_score": "integer (0–100)"
  },
  "case_summary": "string",
  "flags": ["string"]
}
```

### Key Schema Decisions

- **`aml_referenced_as_precedent`** — Boolean flag for the precedent/conviction distinction (Section 12). Any case where this is `true` and `verdict` is `CONVICTED` warrants manual review — it is the most likely failure mode.
- **`flags`** — free-text array for model-surfaced anomalies via the `raise_flag` tool: conflicting charges, incomplete documentation, ambiguous entity structure.
- **`sic_codes` as an array** — enforces multi-code classification. A single-value field would have been architecturally easier and analytically weaker.
- **`confidence_score` on verdict, not just SIC** — the model expresses uncertainty on the legal verdict as well as the business classification. Both are needed to triage outputs for manual review.

---

## 10. Streamlit Results Viewer

`streamlit_app.py` provides a front-end for inspecting processed cases without reading raw JSON. Key design decisions:

- **Reasoning chain is always visible** — not collapsed or hidden. The point of forcing reasoning in the system instruction is to make it inspectable; hiding it in the UI defeats that.
- **Confidence score is prominently surfaced** — outputs below a defined threshold (currently 50%) are flagged visually for review.
- **`aml_referenced_as_precedent` flag is highlighted** — cases where this is `true` get a distinct visual treatment to immediately draw attention during review.
- **SIC codes rendered as a list with individual confidence scores** — not as a single value.
- **Flags rendered separately** — anomalies raised by the model during processing are surfaced distinctly from the main reasoning chain.

The viewer is not the primary output of the pipeline. It is the review interface for cases requiring human inspection.

<img width="1902" height="984" alt="Screenshot 2026-06-24 at 12 29 07 pm" src="https://github.com/user-attachments/assets/ca44cdd2-1997-45ca-a679-ce9030343060" />

<img width="1902" height="984" alt="Screenshot 2026-06-24 at 12 29 19 pm" src="https://github.com/user-attachments/assets/baa54adc-a7c8-482a-a967-9ffbeac0b509" />

<img width="1902" height="984" alt="Screenshot 2026-06-24 at 12 31 35 pm" src="https://github.com/user-attachments/assets/3cd5e914-3dc9-476c-8a0c-576407c9e504" />

---

## 11. Findings

> ⚠️
> **Important caveat:** The sample size is **100 cases**, of which **19** returned a verdict of `CONVICTED` for AML offences, which saw **100 Defendants** charged and convicted for crimes under the POCA 2002. The initial run of 100 cases saw **1171 Total Defendants**. One finding that I found very interesting within my batch of randomly selected cases, 'R v Herbert Charles Austin' saw a confirmed conviction - but no application of statutory law as per the instructions. Further analysis reveals the agent had recognised the crimes had taken place prior to the introduction of POCA 2002, having been committed in 2000, meaning our system prompts worked very well in making the agent strict in its judgement. It's analysis still picked up on the 'CONVICTED' status.
>
> Our initial hypothesis of looking in the legal sector, before branching out to other SIC Codes saw Solicitors account for a small number of the defendants seen in the case filings. 48 Defendants in total, with only **2** that were convicted of AML offences,  with a further **2** awaiting appropriate charges and **12** defendants that had not finished proceedings for their cases. Our initial 'Better Call Saul' hypothesis holds some weight considering it was the 6th most common SIC Code found in our outputs. The full table tells a story of the most common SIC Codes found in AML Cases, though a few of them can be explained as institutions that are often used or report AML offences, hence their frequent appearance in findings.
> 
> Overall, the number of cases we processed in 4 batches does not provide a conclusive judgement, though it does reveal an interest trend in the frequency of certain businesses in AML proceedings.
>
> Due to the sheer volume of outputs, I have a sample of cases that cross all three categories that can be used in the Streamlit app/JSON Reader, as well as the full Excel output of all cases for explaratory analysis.

### Verdict Distribution (Defendants)

| Verdict | Count | % of Sample |
|---|---|---|
| CONVICTED | 165 | 14% |
| ACQUITTED | 62 | 5% |
| CHARGED/PENDING | 72 | 6% |
| MENTIONED ONLY | 570 | 48% |
| NOT FINALISED | 302 | 25% |

### SIC Code Patterns

Early patterns are emerging around certain SIC code clusters appearing disproportionately in convicted cases:

- **[96090]** — [Other service activities n.e.c.] ([**23**] occurrences out of **45** total)
- **[49410]** — [Freight transport by road] ([**17**] occurrences out of **21** total) 
- **[64999]** — [Financial intermediation not elsewhere classified] ([**15**] occurrences out of **78** total)
	
I wouldn't consider these wholly consistent with existing AML typology literature — but these initial findings cannot be treated as confirmatory at this sample size.

### Confidence Score Distribution

Mean confidence across all verdicts: **90%**.
`UNCLEAR` verdicts returned a mean of **[0]%**, providing complete face validity — the model is performing to the level it was designed to.

---

## 12. A Notable LLM Quirk — The Divergent Verdict Problem

This section exists because it has direct implications for anyone building LLM-based legal reasoning tools — and because the architectural response to it shaped several design decisions in this pipeline.

My mentor and I both ran the case **D v Law Society** through our respective setups and arrived at **different verdicts**.

### The Root Cause

The case makes references to POCA 2002 — specifically as legal precedent cited by one party. The **primary conviction** is for a separate offence. The AML charge was not upheld.

Models without explicit instruction to distinguish between these two scenarios frequently misclassify this as an AML conviction. The model sees POCA 2002, sees conviction language, and pattern-matches to `CONVICTED`. It is not wrong that AML appears in the case — it is wrong about what role it plays.

This is not a hallucination problem. It is a **domain knowledge problem**. Citing a statute as precedent is structurally different from being convicted under it. A lawyer reads these as categorically different things. A language model, without explicit instruction, often does not.

### Why It Was Anticipated

Two years of law at A Level meant this ambiguity was recognisable during design — not in retrospect. The `aml_referenced_as_precedent` boolean, the `raise_flag` tool, and the explicit scope boundary in the system instruction were all built before this case was run. The divergent verdict with my mentor validated the design decision.

### Implication for LLM Legal Tooling

Any LLM-based legal classifier operating on case law must explicitly handle the distinction between:

1. A statute appearing as the **basis of conviction**
2. A statute appearing as **cited precedent, a dropped charge, or regulatory context**

Failing to encode this in the system instruction will systematically inflate conviction rates in any corpus containing complex, multi-charge cases — which is most serious case law.

---

## 13. Misclassification Taxonomy

Section 12 documents the single most striking misclassification event in detail. This section steps back and categorises the full set of known failure modes observed across the pipeline — both those encountered in practice and those anticipated by design. The distinction between the two is noted explicitly, because a failure mode you anticipated and mitigated is a different class of risk from one you discovered after the fact.

Understanding these failure modes is the precondition for expanding the corpus confidently. At small sample sizes, individual misclassifications are manually detectable. At scale, they become systematic noise unless the taxonomy is documented and the mitigations are architectural.

---

### Type 1: Precedent/Conviction Conflation

**Classification:** Encountered in practice, mitigated by design  
**Severity:** High — directly inflates conviction rate

**Description:** The model classifies a case as `CONVICTED` when POCA 2002 appears in the judgment as cited precedent rather than as the basis of the actual conviction. The model correctly identifies the presence of AML-related statute; it incorrectly infers that presence as an outcome.

**Why it occurs:** Without domain grounding, the co-occurrence of POCA 2002 and conviction language is sufficient for the model to pattern-match to a positive verdict. It is not reasoning about the *role* of the statute — it is pattern-matching on its *presence*.

**Mitigation:** Explicit scope boundary in the system instruction; `aml_referenced_as_precedent` boolean in the output schema; `raise_flag` tool for surfacing ambiguous cases. The `aml_referenced_as_precedent` flag never fired as `true` alongside a `CONVICTED` verdict in the current corpus — but this should be interpreted cautiously. Two readings are equally valid: the safeguard worked as designed, *or* the current sample has not included a sufficiently ambiguous case to genuinely stress-test it. At scale, both possibilities need to be held open.

---

### Type 2: Cross-Statute Conflation

**Classification:** Anticipated by design, not yet observed in practice  
**Severity:** Medium — inflates conviction rate for wrong statutory basis

**Description:** The model identifies a financial crime conviction but attributes it to POCA 2002 when the actual conviction is under a related but distinct statute. The known confusables in this corpus are:

| Statute | Nature of Confusion |
|---|---|
| **Criminal Justice and Police Act 2001 (CJPA 2001)** | Overlapping financial crime provisions; older cases may reference CJPA 2001 alongside or instead of POCA 2002 |
| **Police and Criminal Evidence Act 1984 (PACE 1984)** | Procedural statute frequently cited in financial crime cases; investigative powers can be confused with substantive offence provisions |
| **Serious Crime Act 2007** | Serious crime prevention orders and facilitation provisions overlap conceptually with POCA 2002 arrangements offences |

**Why it occurs:** These statutes co-occur frequently with POCA 2002 in serious financial crime judgments. A model without explicit statutory disambiguation may conflate the legislative basis of a conviction when multiple statutes are cited across the same judgment.

**Mitigation:** The `lookup_poca_section` tool keeps statutory reasoning anchored to POCA 2002 specifically. The system instruction explicitly names POCA 2002 sections rather than referring generically to "money laundering." The `poca_sections_identified` field in the output schema forces the model to name the specific sections it applied — making cross-statute conflation detectable in the output rather than buried in the reasoning.

**Current status:** Observed twice in the corpus to date. The first instance was a crime that was committed before the introduction of the 2002 POCA. The second referenced Criminal Justice and Police Act 2001 (CJPA 2001), but flagged this upon retrieval.

---

### Type 3: Dropped Charge Misreading

**Classification:** Anticipated by design, borderline with Type 1  
**Severity:** High — directly inflates conviction rate

**Description:** The model returns `CONVICTED` when an AML charge was brought but not upheld — either acquitted, discontinued, or substituted for a lesser offence. This is distinct from Type 1 (precedent) in that the AML charge was actually *tried* in this case; the error is in reading the outcome of that charge.

**Why it occurs:** Judgment language around acquittals and dropped charges can be structurally similar to conviction language, particularly in multi-defendant, multi-count cases. The model may encounter "the defendant was convicted" in the context of a different count and associate it with the AML charge.

**Mitigation:** The mandatory reasoning requirement in the system instruction forces the model to trace the outcome of each charge individually before invoking `record_verdict`. The `aml_referenced_as_precedent` flag partially covers this case — though a dropped charge is not technically a precedent, the flag is designed broadly enough to catch cases where AML appeared without producing a conviction. Review of low-confidence `CONVICTED` verdicts via the Streamlit viewer is the primary detection mechanism at current scale.

---

### Taxonomy Summary

| Type | Description | Encountered | Mitigated By |
|---|---|---|---|
| 1 | Precedent/conviction conflation | Yes | System instruction scope boundary · `aml_referenced_as_precedent` flag |
| 2 | Cross-statute conflation | Yes (anticipated) | `lookup_poca_section` tool · explicit section naming · `poca_sections_identified` field |
| 3 | Dropped charge misreading | No (anticipated) | Mandatory reasoning chain · `aml_referenced_as_precedent` flag · low-confidence review |

The fact that Types 2 and 3 have not been observed in huge quantities in practice is not grounds for removing their mitigations. It is grounds for ensuring those mitigations remain structurally intact as the corpus scales and case complexity increases.

---

## 14. Limitations

### Sample Size
The most significant constraint. **100** cases is sufficient to demonstrate the tool works and the approach is sound. It is not sufficient to evidence the hypothesis. Any pattern at this scale is a signal to investigate, not a finding to publish.

### Model Confidence Calibration
Confidence scores are relative, not calibrated. 85% means the model is more certain than when it returns 60% — it does not mean the model is correct 85% of the time. True calibration requires a labelled ground-truth dataset, which does not yet exist for this corpus.

### Single Model Evaluation
All cases are processed through a single model configuration (Gemini). Running divergent cases through a second model and comparing outputs would increase confidence in verdicts, particularly in the `UNCLEAR` category.

### SIC Code Fuzzy Matching
Fuzzy matching against business descriptions is imperfect. Where the defendant's business is described in unusual terms or where the business name gives limited indication of its nature, SIC matches may be unreliable. The per-code confidence score surfaces this — but it adds a second layer of uncertainty on top of the verdict confidence.

### AkomaNtoso Schema Variability
Not all BAILII documents conform identically to the AkomaNtoso standard. Older judgments in particular show structural variation — inconsistent section tagging, missing metadata elements — that `extractor.py` handles heuristically in some cases. This is a data quality constraint, not a model one.

---

## 15. Future Work

### Near-Term
- **Expand the corpus** — the single highest-impact change. **1,000** cases minimum before any pattern can be treated as evidenced
- **SQL database layer** — PostgreSQL to replace Excel export as the primary storage layer, enabling structured querying at scale
- **Multi-model validation** — route `UNCLEAR` and low-confidence cases through a second model; flag divergent verdicts for manual review

### Medium-Term
- **Graph database for entity relationships** — Neo4j or Amazon Neptune to model relationships between defendants, businesses, legal representatives, and courts. Moves the analysis from tabular to relational; opens network-level pattern detection
- **Time series layer** — conviction pattern tracking over time, linked to external events (regulatory changes, enforcement campaigns, legislative updates)
- **Automated BAILII ingestion** — scheduled pipeline to ingest new judgments as published, rather than manual case-by-case loading

### Long-Term
- **Ground truth dataset** — collaboration with a legal professional to build a labelled evaluation set, enabling genuine confidence calibration and systematic model evaluation
- **Cross-jurisdiction expansion** — AkomaNtoso is used across multiple jurisdictions. The pipeline architecture is jurisdiction-agnostic in principle; extending to Scottish, Northern Irish, or international case law is a data sourcing problem, not an architectural one

---

## 16. Appendix

### A. POCA 2002 — Relevant Sections[Sample]

| Section | Title | Offence Summary |
|---|---|---|
| s.327 | Concealing etc. | Concealing, disguising, converting, transferring, or removing criminal property |
| s.328 | Arrangements | Entering into or becoming concerned in an arrangement facilitating acquisition, retention, use or control of criminal property |
| s.329 | Acquisition, use and possession | Acquiring, using, or possessing criminal property |

### B. Tools & Technologies

| Component | Technology |
|---|---|
| Language | Python |
| LLM | Gemini API (gemini-3.5-flash) | 
| Orchestration | `main.py` — custom agentic loop |
| XML Ingestion | `extractor.py` — AkomaNtoso parser |
| POCA Reference | `poca_loader.py` — shared in-memory dict |
| Function Calling Schema | `tools.py` — Gemini tool definitions |
| Output Assembly | `executor.py` |
| Results Viewer | Streamlit (`streamlit_app.py`) |
| SIC Code Lookup | UK SIC 2007 (.csv) |
| Output Format | Structured JSON |
| Export | Excel (.xlsx) |
| Retry Logic | `_send_with_retry()` — exponential backoff with jitter |
| Future DB | PostgreSQL → Neo4j |

### C. Case Log

| Case Reference | Case Name | Verdict | Confidence | Primary SIC | AML as Precedent |
|---|---|---|---|---|---|
| [ref] | [name] | [verdict] | [%] | [code] | [true/false] |

*Full case log available on request.*

---

*This write-up is a technical companion to the LinkedIn Article and post summarising this project. It is not legal advice. All case analysis is experimental and should not be relied upon for any legal or compliance purpose. This project represents independent research and does not reflect the views of my employer.*
