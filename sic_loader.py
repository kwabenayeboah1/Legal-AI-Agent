"""
Loads the UK SIC 2007 (Standard Industrial Classification) reference list
from sic_codes.csv and formats it for injection into the Gemini prompt.

main.py calls format_for_prompt() once at startup and embeds the result
directly in SYSTEM_PROMPT/SIC_PROMPT_BLOCK, so the model classifies each
defendant's business activity only against this fixed code list — never
against its own general knowledge of SIC codes. classify_sic_codes (see
tools.py / executor.py) then has to return codes drawn from exactly this
set for the classification to be meaningful downstream.
"""
import csv

def load_sic_codes(filepath: str) -> list[dict]:
    """
    Reads sic_code/sic_desc columns from the CSV at filepath into a list of
    {'code', 'description'} dicts. Rows missing either column are silently
    skipped rather than raising, since the CSV is externally sourced and may
    contain header/blank rows that don't represent a real code.
    """
    codes = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('sic_code', '').strip()
            desc = row.get('sic_desc', '').strip()
            if code and desc:
                codes.append({'code': code, 'description': desc})

    print(f"Loaded {len(codes)} SIC codes from {filepath}")
    return codes


def format_for_prompt(sic_codes: list[dict]) -> str:
    """Renders the loaded code list as plain 'code: description' lines, one
    per row, for embedding directly into the LLM system prompt."""
    return '\n'.join(f"{s['code']}: {s['description']}" for s in sic_codes)