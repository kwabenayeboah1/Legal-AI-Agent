import xml.etree.ElementTree as ET
import re


# POCA 2002 section pattern — covers all Parts (2, 5, 7, 8 and edge cases)
# Matches: s327, s327(1), s333A, s303Z1, s286A, s245C
_POCA_SECTION_RE = re.compile(
    r'\b(?:section|s\.?)\s*'
    r'(\d{1,3}[A-Z]?(?:\(\d+\))?(?:[A-Z]\d*)?)',
    re.IGNORECASE
)

# All known valid POCA 2002 section prefixes — used to filter generic statute refs
_POCA_VALID_PREFIXES = {
    # Part 2 — Confiscation
    "6", "7", "8", "10", "40", "41", "75", "84",
    # Part 5 — Civil Recovery
    "240", "241", "242", "243", "266", "286A", "294", "295", "298",
    "303Z1", "306",
    # Part 7 — Money Laundering Offences
    "327", "327(1)", "328", "329", "330", "331", "332", "333", "333A",
    "335", "336", "337", "338", "339", "340", "342",
    # Part 8 — Investigations
    "341", "341A", "342", "353", "355", "357", "358", "362", "363", "370",
    # Other
    "16", "17", "444", "245C",
}


def _normalise_section(raw: str) -> str:
    """Normalise a raw regex match to a canonical form like 's327' or 's333A'."""
    s = raw.strip().lstrip("s").lstrip("S").lstrip(".")
    # Remove leading zeros but preserve letter suffixes
    s = re.sub(r'^0+', '', s)
    return f"s{s}"


def _is_valid_poca(normalised: str) -> bool:
    """Return True if the section number (without leading 's') is a known POCA provision."""
    num = normalised.lstrip("s")
    # Exact match
    if num in _POCA_VALID_PREFIXES:
        return True
    # Prefix match for subsection variants e.g. s327(1), s333A(2)
    for prefix in _POCA_VALID_PREFIXES:
        if num.startswith(prefix) and len(num) > len(prefix):
            return True
    return False


def extract_from_xml(file_path: str) -> tuple[str, dict]:
    """
    Parses a UK National Archives Akoma Ntoso XML legal judgment.

    Returns:
        body_text   — clean prose extracted from the judgment body for LLM consumption
        xml_metadata — structured dict of pre-extracted structural fields seeded into
                       pipeline_state before the first Gemini call
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except Exception as e:
        raise ValueError(f"Failed to parse XML file {file_path}: {e}")

    def clean_tag(tag: str) -> str:
        return tag.split('}')[-1] if '}' in tag else tag

    def get_ns(tag: str) -> str:
        """Return the namespace URI portion of a Clark-notation tag."""
        return tag.split('}')[0].lstrip('{') if '}' in tag else ""

    xml_metadata: dict = {
        "neutral_citation": None,
        "citation":         None,
        "court":            None,
        "date":             None,
        "judge":            None,
        "docket_number":    None,
        "parties":          [],
        "poca_sections":    [],
        "cited_cases":      [],
    }

    body_text_parts: list[str] = []

    # ── Role tracking for party extraction ────────────────────────────────────
    # Map eId → role label from TLCRole elements
    role_map: dict[str, str] = {}
    # Map eId → display name from TLCPerson elements
    person_map: dict[str, str] = {}

    # ── Single-pass traversal ──────────────────────────────────────────────────
    for elem in root.iter():
        tag  = clean_tag(elem.tag)
        text = elem.text.strip() if elem.text and elem.text.strip() else None
        tail = elem.tail.strip() if elem.tail and elem.tail.strip() else None

        # Body text accumulation — skip meta/style/presentation nodes
        if tag not in {
            "meta", "identification", "lifecycle", "references",
            "proprietary", "presentation", "style", "FRBRWork",
            "FRBRExpression", "FRBRManifestation",
        }:
            if text:
                body_text_parts.append(text)
            if tail:
                body_text_parts.append(tail)

        # ── Metadata extraction ────────────────────────────────────────────

        # National Archives proprietary block: uk:cite, uk:court, uk:number
        ns = get_ns(elem.tag)
        if "nationalarchives" in ns or "caselaw" in ns:
            if tag == "cite" and text:
                xml_metadata["neutral_citation"] = text
                xml_metadata["citation"]         = text
            elif tag == "court" and text:
                # uk:court gives the short court code e.g. "EWHC-QBD"
                xml_metadata["court"] = text
            elif tag == "number" and text:
                xml_metadata["docket_number"] = text

        # Standard Akoma Ntoso tags
        if tag == "neutralCitation" and text:
            xml_metadata["neutral_citation"] = text
            xml_metadata["citation"]         = text

        elif tag == "FRBRdate":
            date_val = elem.get("date")
            name_val = elem.get("name", "")
            if date_val and name_val in ("judgment", "decision"):
                xml_metadata["date"] = date_val

        elif tag == "docDate":
            date_val = elem.get("date") or text
            if date_val:
                xml_metadata["date"] = date_val

        elif tag == "FRBRname":
            # FRBRname carries the human-readable case name — used as citation fallback
            val = elem.get("value") or text
            if val and not xml_metadata["neutral_citation"]:
                xml_metadata["citation"] = val

        elif tag == "FRBRnumber":
            val = elem.get("value") or text
            if val and not xml_metadata["docket_number"]:
                xml_metadata["docket_number"] = val

        # Parties and roles from TLC* reference elements
        elif tag == "TLCRole":
            eid      = elem.get("eId", "")
            show_as  = elem.get("showAs", "")
            if eid and show_as:
                role_map[eid] = show_as

        elif tag == "TLCPerson":
            eid      = elem.get("eId", "")
            show_as  = elem.get("showAs", "")
            if eid and show_as:
                person_map[eid] = show_as
                # Detect judge by convention: eId starts with "judge-"
                if eid.startswith("judge-") and not xml_metadata["judge"]:
                    xml_metadata["judge"] = show_as

        elif tag == "TLCOrganization":
            eid      = elem.get("eId", "")
            show_as  = elem.get("showAs", "")
            if eid and show_as:
                person_map[eid] = show_as

        # Legacy docJudge / judge elements
        elif tag in ("docJudge", "judge"):
            if text and not xml_metadata["judge"]:
                xml_metadata["judge"] = text

        elif tag == "party" and text:
            # The XML links the role using the 'as' attribute (e.g., as="#claimant")
            role_ref = elem.get("as", "").lstrip("#")
            
            # Match the reference to the TLCRole dictionary you built earlier
            role_label = role_map.get(role_ref, role_ref.capitalize())
            
            # Format it nicely for the LLM context block
            if role_label:
                xml_metadata["parties"].append(f"{text} ({role_label})")
            else:
                xml_metadata["parties"].append(text)

        # Cited case references
        elif tag == "ref":
            href  = elem.get("href", "")
            rtext = text or ""
            if rtext and ("/id/" in href or "caselaw" in href or "[" in rtext):
                xml_metadata["cited_cases"].append({
                    "text": rtext,
                    "href": href
                })

    # ── Post-pass: build parties list from TLCPerson if no <party> elements ──
    if not xml_metadata["parties"] and person_map:
        for eid, name in person_map.items():
            if not eid.startswith("judge-"):
                xml_metadata["parties"].append(name)

    # ── Fallback: regex citation from body text ────────────────────────────────
    body_text = "\n".join(body_text_parts)

    if not xml_metadata["neutral_citation"]:
        cite_match = re.search(
            r'\[(\d{4})\]\s+(?:EWHC|EWCA|UKSC|UKHL|EWCOP|EWHC)\s+\d+(?:\s+\(\w+\))?',
            body_text
        )
        if cite_match:
            xml_metadata["neutral_citation"] = cite_match.group(0)
            xml_metadata["citation"]         = cite_match.group(0)

    # ── POCA section extraction — full Act coverage ────────────────────────────
    raw_matches = _POCA_SECTION_RE.findall(body_text)
    if raw_matches:
        normalised    = [_normalise_section(m) for m in raw_matches]
        valid_and_unique = sorted(
            {s for s in normalised if _is_valid_poca(s)},
            key=lambda x: (re.sub(r'[^0-9]', '', x).zfill(5), x)
        )
        xml_metadata["poca_sections"] = valid_and_unique

    return body_text, xml_metadata
