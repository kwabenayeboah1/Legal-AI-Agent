import json
from pathlib import Path

# Single source of truth for POCA 2002 reference data.
# Both main.py (fetch/update) and executor.py (enrichment) import the SAME
# dict object from here and mutate it in place — not separate copies each
# loaded independently — so a fetch in main.py is immediately visible to
# executor.py's enrichment without needing a second load.

POCA_DEF_FILE = Path("poca_reference.json")

POCA_SECTIONS: dict = {}


def load_poca_definitions() -> dict:
    """
    Loads (or reloads) poca_reference.json from disk into the shared
    POCA_SECTIONS dict IN PLACE, and returns that same object.
    Safe to call multiple times — always refreshes the same dict instance
    rather than creating a new one.
    """
    if POCA_DEF_FILE.exists():
        try:
            with open(POCA_DEF_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            POCA_SECTIONS.clear()
            POCA_SECTIONS.update(data)
        except json.JSONDecodeError as e:
            print(f"  ⚠ JSON format error in poca_reference.json: {e}")
    return POCA_SECTIONS


def save_poca_definitions(sections: dict) -> None:
    """
    Writes the POCA reference dictionary back to disk.
    Called by main.py's update_poca_reference() after Gemini fetches data for
    a section this file didn't already have, so the next run doesn't need to
    re-fetch it.
    """
    with open(POCA_DEF_FILE, "w", encoding="utf-8") as f:
        json.dump(sections, f, indent=4)
