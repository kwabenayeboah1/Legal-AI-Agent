"""
Receives Gemini's function-call results for the case currently being
processed and assembles them into the final structured case JSON.

Wiring (see main.py's run_pipeline): every time the model emits a function
call declared in tools.py, main.py hands it to execute_tool(), which stashes
the raw args into the module-level pipeline_state dict. Once the chat has
finished calling all three tools for a case, main.py calls build_output(),
which reads pipeline_state back out, deduplicates/cross-references the
three tool outputs against each other (defendants <-> SIC classifications
by name, cited POCA sections <-> reference data), and returns the single
dict that gets written to outputs/<case>/*.json.

pipeline_state is intentionally module-level and mutable rather than passed
around as an argument: main.py's batch_process() calls pipeline_state.clear()
between cases, so this module only ever holds state for the one case
currently in flight.
"""
import json
from poca_loader import load_poca_definitions

# ── POCA 2002 reference data ───────────────────────────────────────────────────
# Loaded from poca_reference.json — the same file main.py reads from and writes
# to via fetch_missing_poca_sections/update_poca_reference. This used to be an
# inlined dict here, which silently drifted out of sync with poca_reference.json
# (main.py fetches were never reflected in this enrichment). Do not re-inline —
# poca_loader.py is the single source of truth.

POCA_SECTIONS = load_poca_definitions()
# ── Pipeline state ─────────────────────────────────────────────────────────────

pipeline_state = {}


def execute_tool(name: str, args: dict) -> str:
    """
    Dispatches one Gemini function call by name into pipeline_state, and
    returns the JSON string main.py sends back to the chat as the tool's
    result (Gemini's function-calling protocol expects a response for every
    call before it continues).

    Defendants and SIC classifications are deduplicated by lowercased name
    here rather than left for build_output() to sort out, since the model
    can occasionally re-emit the same entity across calls. For duplicate
    defendants, the entry with the longer verdict_reasoning wins on the
    assumption that more detail means a more complete extraction; for
    duplicate classifications, the first one seen wins (SIC classification
    calls don't accumulate detail across repeats the way defendant reasoning
    can).
    """

    if name == "extract_case_metadata":
        pipeline_state["case"] = args
        return json.dumps({"status": "ok"})

    if name == "extract_defendants":
        seen = {}
        for d in args.get("defendants", []):
            key = d["name"].strip().lower()
            if key not in seen:
                seen[key] = d
            else:
                existing = seen[key]
                if len(d.get("verdict_reasoning", "")) > len(existing.get("verdict_reasoning", "")):
                    seen[key] = d
        pipeline_state["defendants"] = list(seen.values())
        return json.dumps({"status": "ok", "unique_defendants": len(seen)})

    if name == "classify_sic_codes":
        seen = {}
        for c in args.get("classifications", []):
            key = c["name"].strip().lower()
            if key not in seen:
                seen[key] = c
        pipeline_state["classifications"] = list(seen.values())
        return json.dumps({"status": "ok"})

    return json.dumps({"error": f"Unknown tool: {name}"})


def _enrich_poca_sections(sections: list[str]) -> dict:
    """
    For each cited section string (e.g. 's327', 's335'), look up the full
    reference data and return a dict keyed by section string.
    Unknown sections get a minimal fallback entry so the Streamlit tag still renders.
    """
    enriched = {}
    for s in sections:
        info = POCA_SECTIONS.get(s)
        if info:
            enriched[s] = {
                "title":                info.get("title", ""),
                "full":                 info.get("full", ""),
                "elements":             info.get("elements", []),
                "notes":                info.get("notes", ""),
                "part_chapter":         info.get("part_chapter", ""),
                "confidence":           info.get("confidence", ""),
                "confidence_reasoning": info.get("confidence_reasoning", ""),
            }
        else:
            enriched[s] = {
                "title":                "Proceeds of Crime Act 2002",
                "full":                 f"Statutory provision {s} of the Proceeds of Crime Act 2002.",
                "elements":             [],
                "notes":                "Detailed reference data not available for this section.",
                "part_chapter":         "",
                "confidence":           "",
                "confidence_reasoning": "",
            }
    return enriched


def build_output() -> dict:
    """
    Assembles the final per-case JSON from whatever execute_tool() has
    accumulated in pipeline_state for the case currently in flight. Called
    once per case, after the model has finished all its tool calls, from
    main.py's run_pipeline().

    Cross-references the three tool outputs by defendant name (case
    metadata, defendants, SIC classifications aren't naturally linked
    otherwise) and enriches every cited POCA section with full reference
    data via _enrich_poca_sections(). Falls back to extractor.py's
    xml_metadata for judge/docket/parties whenever the model left those
    fields blank, so structural facts already visible in the XML are never
    lost just because the model omitted them.
    """
    case = pipeline_state.get("case", {})

    sic_lookup = {
        c["name"].strip().lower(): c
        for c in pipeline_state.get("classifications", [])
    }

    defendants_out = []
    for d in pipeline_state.get("defendants", []):
        key            = d["name"].strip().lower()
        classification = sic_lookup.get(key, {})

        # Normalise SIC code entries:
        #   - Streamlit reads 'code' not 'sic_code' — normalise whichever the model returned
        #   - Confidence formatted as "N%" string
        #   - Per-code 'reasoning' field preserved if present
        sic_codes = []
        for sic in classification.get("sic_codes", []):
            code_val = sic.get("code") or sic.get("sic_code") or "—"
            raw_conf = sic.get("confidence", 0)
            try:
                conf_int = int(str(raw_conf).replace("%", "").strip())
            except (ValueError, TypeError):
                conf_int = 0
            sic_codes.append({
                "code":        code_val,
                "description": sic.get("description", ""),
                "confidence":  f"{conf_int}%",
                "reasoning":   sic.get("reasoning", ""),
            })

        defendants_out.append({
            "name":                   d.get("name"),
            "role":                   d.get("role"),
            "verdict":                d.get("verdict"),
            "verdict_reasoning":      d.get("verdict_reasoning"),
            "poca_section":           d.get("poca_section"),
            "poca_section_reasoning": d.get("poca_section_reasoning"),
            "key_facts":              d.get("key_facts", []),
            "sic_codes":              sic_codes,
            "sic_overall_reasoning":  classification.get("overall_reasoning"),
        })

    # Enrich every cited POCA section with full reference data
    cited_sections = case.get("poca_sections", [])
    poca_enriched  = _enrich_poca_sections(cited_sections)

    # Judge / docket / parties — model returns these via extract_case_metadata.
    # Fall back to xml_metadata pre-populated by extractor.py so structural
    # fields are never silently dropped even if the model omits them.
    xml_meta = pipeline_state.get("xml_metadata", {})
    judge   = case.get("judge")         or xml_meta.get("judge")
    docket  = case.get("docket_number") or xml_meta.get("docket_number")
    parties = case.get("parties")       or xml_meta.get("parties", [])

    return {
        "case_name":              case.get("case_name"),
        "case_reference":         case.get("case_reference"),
        "court":                  case.get("court"),
        "jurisdiction":           case.get("jurisdiction"),
        "case_date":              case.get("case_date"),
        "judge":                  judge,
        "docket_number":          docket,
        "parties":                parties,
        "case_summary":           case.get("case_summary"),
        "aml_status":             case.get("aml_status"),
        "aml_status_reasoning":   case.get("aml_status_reasoning"),
        "poca_sections":          cited_sections,
        "poca_sections_enriched": poca_enriched,
        "poca_analysis":          case.get("poca_analysis"),
        "precedent_value":        case.get("precedent_value"),
        "key_findings":           case.get("key_findings", []),
        "defendants":             defendants_out,
        "defendant_count":        len(defendants_out),
    }
