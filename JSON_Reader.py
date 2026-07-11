"""
Standalone CLI viewer for the JSON case files produced by main.py's batch
pipeline (executor.py's build_output()) under outputs/<case>/*.json.

This is independent of streamlit_app.py — same underlying case JSON, but
rendered as Rich tables/panels in the terminal instead of a web UI, for
quickly spot-checking pipeline output without starting Streamlit. Run
directly (`python JSON_Reader.py`): it walks outputs/ for JSON files, lets
you pick which to load, optionally filter by text/AML status/POCA section,
then lets you select one case at a time to view in full via display_full_case().
"""
import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.align import Align

console = Console()

# ── Colour Styles ─────────────────────────────────────────────────────────────
AML_COLOURS = {
    "confirmed verdict": "bold red",
    "alleged/charged":   "bold yellow",
    "precedent only":    "bold blue",
    "not aml":           "dim",
}

VERDICT_COLOURS = {
    "convicted":       "bold red",
    "acquitted":       "bold green",
    "charged/pending": "bold yellow",
    "not finalized":   "cyan",
    "mentioned only":  "dim",
}

def aml_style(status: str) -> str:
    return AML_COLOURS.get((status or "").lower(), "white")

def verdict_style(verdict: str) -> str:
    return VERDICT_COLOURS.get((verdict or "").lower(), "white")


# ── Table-Based Renderers ──────────────────────────────────────────────────────

def display_case_header(case: dict):
    """Prints a massive, centered title banner for the case."""
    case_name = case.get("case_name", "Unknown Case")
    case_ref  = case.get("case_reference", "No Reference")
    
    title_text = f"[bold white]{case_name}[/bold white]\n[dim cyan]{case_ref}[/dim cyan]"
    
    console.print("\n")
    console.print(
        Panel(
            Align.center(title_text), 
            box=box.HEAVY, 
            border_style="blue", 
            padding=(1, 2)
        )
    )

def display_metadata_table(case: dict):
    """Renders the core case information in a clean metadata grid."""
    table = Table(box=box.DOUBLE_EDGE, show_header=False, expand=True, border_style="cyan")
    table.add_column("Field", style="bold cyan", width=24)
    table.add_column("Value", style="white")

    status = case.get("aml_status", "—")
    
    # Format the parties list into a readable string
    parties = case.get("parties", [])
    parties_str = "\n".join(parties) if isinstance(parties, list) and parties else "—"
    
    fields = [
        ("🏛️ Case Name",       case.get("case_name", "—")),
        ("📑 Reference",       case.get("case_reference", "—")),
        ("🏢 Court",           case.get("court", "—")),
        ("🌍 Jurisdiction",    case.get("jurisdiction", "—")),
        ("⚖️ Judge",            case.get("judge", "—")),              
        ("🗃️ Docket Number",   case.get("docket_number", "—")),      
        ("📅 Case Date",       case.get("case_date", "—")),
        ("🚨 AML Status",      f"[{aml_style(status)}]{status}[/]"),
        ("👥 Defendant Count", str(case.get("defendant_count", "—"))),
        ("💼 Parties",         parties_str),                         
        ("📄 Source File",     case.get("source_file", "—")),
    ]

    for label, value in fields:
        if value and value != "—":
            table.add_row(label, value)
            
    console.print("\n")
    console.print(table)


def display_narrative_sections(case: dict):
    """Displays Case Summary, AML reasoning, and Precedent Value in clean rows."""
    if case.get("case_summary"):
        console.print(Panel(case.get("case_summary").strip(), title="[bold cyan]Case Summary[/bold cyan]", border_style="cyan", expand=True))
    
    if case.get("aml_status_reasoning"):
        console.print(Panel(case.get("aml_status_reasoning").strip(), title="[bold yellow]AML Classification Reasoning[/bold yellow]", border_style="yellow", expand=True))
        
    if case.get("precedent_value"):
        console.print(Panel(case.get("precedent_value").strip(), title="[bold green]Precedent Value & Authority[/bold green]", border_style="green", expand=True))

    if case.get("poca_analysis"):
        console.print(Panel(case.get("poca_analysis").strip(), title="[bold purple]POCA 2002 Statutory Analysis[/bold purple]", border_style="purple", expand=True))


def display_poca_sections_table(case: dict):
    """Formats all referenced POCA sections into a neat, unified master table."""
    sections = case.get("poca_sections", [])
    enriched = case.get("poca_sections_enriched", {})

    if not sections:
        return

    table = Table(title="[bold purple]POCA 2002 Sections Cited[/bold purple]", box=box.HEAVY_HEAD, show_lines=True, expand=True, header_style="purple")
    table.add_column("Section", style="bold purple", justify="center", width=10)
    table.add_column("Title & Overview", style="white", width=40)
    table.add_column("Statutory Elements & Notes", style="dim white")

    for section in sections:
        info = enriched.get(section, {})
        title = info.get("title", "No reference data")
        full = info.get("full", "")
        elements = info.get("elements", [])
        notes = info.get("notes", "")

        # Format elements cleanly as bullets
        elements_str = ""
        if elements:
            elements_str = "\n".join([f"• {el}" for el in elements])
        if notes:
            elements_str += f"\n\n[italic yellow]Note: {notes}[/italic yellow]"

        overview = f"[bold]{title}[/bold]\n[dim]{full}[/dim]"
        table.add_row(section, overview, elements_str.strip())

    console.print(table)


def display_key_findings_table(case: dict):
    """Displays findings in a structured checklist-style layout."""
    findings = case.get("key_findings", [])
    if not findings:
        return

    table = Table(title="[bold green]⚖️  Key Judicial Findings[/bold green]", box=box.ROUNDED, show_lines=True, expand=True, header_style="green")
    table.add_column("ID", style="dim green", justify="center", width=5)
    table.add_column("Holding / Principle Established", style="white")

    for i, finding in enumerate(findings, 1):
        table.add_row(f"{i:02d}", finding)

    console.print(table)


def display_defendants_table(case: dict):
    """Presents all defendants and involved parties into a comprehensive grid layout."""
    defendants = case.get("defendants", [])
    if not defendants:
        return

    # Added padding=(1, 1) to give each row a blank line above and below it
    table = Table(
        title="[bold red]👥 Involved Parties / Defendants Data[/bold red]", 
        box=box.ROUNDED,             # 'ROUNDED' is very reliable for rendering lines
        show_lines=True,             # This forces the horizontal lines between rows
        expand=True, 
        header_style="bold red"
    )
    table.add_column("Party Name & Role", style="bold white", width=25)
    table.add_column("Legal Metrics & Reasonings", style="white", width=45)
    table.add_column("Key Case Facts & SIC Classifications", style="white")

    for d in defendants:
        name = d.get("name", "Unknown")
        role = d.get("role", "—")
        verdict = d.get("verdict", "—")
        poca_s = d.get("poca_section", "N/A")
        v_r = d.get("verdict_reasoning", "")
        p_r = d.get("poca_section_reasoning", "")
        facts = d.get("key_facts", [])
        sics = d.get("sic_codes", [])
        overall_sic = d.get("sic_overall_reasoning", "")

        # Column 1: Identity
        v_style = verdict_style(verdict)
        identity = f"[bold]{name}[/bold]\n[dim]{role}[/dim]\n\n[{v_style}]Verdict: {verdict}[/]\n[purple]POCA: {poca_s}[/purple]"

        # Column 2: Legal Metrics Reasoning
        metrics_reasoning = ""
        if v_r:
            metrics_reasoning += f"[cyan]Verdict Reasoning:[/cyan]\n{v_r}\n\n"
        if p_r and poca_s != "N/A":
            metrics_reasoning += f"[purple]POCA Application:[/purple]\n{p_r}"
        if not metrics_reasoning:
            metrics_reasoning = "[dim]No statutory analysis details recorded.[/dim]"

        # Column 3: Facts & SIC data combined
        facts_str = ""
        if facts:
            facts_str += "[bold yellow]Factual Context:[/bold yellow]\n" 
            # Make the bullet cyan, and the text dim white for easier reading
            facts_str += "\n".join([f"[cyan]→[/cyan] [white]{f}[/white]" for f in facts]) + "\n\n"
        
        if sics:
            facts_str += "[yellow]SIC Coding Alignment:[/yellow]\n"
            for sic in sics:
                code = sic.get("code") or sic.get("sic_code") or "—"
                desc = sic.get("description", "—")
                facts_str += f"• [bold math]{code}[/bold math]: {desc}\n"
            if overall_sic:
                facts_str += f"[dim]Overall: {overall_sic}[/dim]"

        table.add_row(identity, metrics_reasoning.strip(), facts_str.strip())

    console.print(table)


def display_full_case(case: dict):
    """Outputs all structured case modules sequentially without prompt interruption."""
    display_case_header(case)
    display_metadata_table(case)
    display_narrative_sections(case)
    display_poca_sections_table(case)
    display_key_findings_table(case)
    display_defendants_table(case)
    console.print("\n" + "═" * console.width + "\n", style="dim")


# ── Runtime Pipeline Data Loading ─────────────────────────────────────────────

def load_case_data(file: Path) -> list[dict]:
    """
    Loads one output JSON file and normalises it to a list of case dicts.
    A file can hold either a single case object or a list of them (batch runs
    write one file per case, but this stays permissive for hand-assembled
    files too). Entries with an "error" key are pipeline failures recorded by
    batch_process() in main.py, not real cases, so they're dropped here.
    """
    with open(file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    elif isinstance(data, list):
        return [c for c in data if isinstance(c, dict) and "error" not in c]
    return []

def search_cases(cases: list[dict], term: str) -> list[dict]:
    """Free-text filter: keeps cases whose full JSON (any field) contains term."""
    term = term.lower()
    return [c for c in cases if term in json.dumps(c).lower()]

def filter_by_aml(cases: list[dict], status: str) -> list[dict]:
    """Keeps cases with an exact (case-insensitive) aml_status match."""
    return [c for c in cases if (c.get("aml_status") or "").lower() == status.lower()]

def filter_by_poca(cases: list[dict], section: str) -> list[dict]:
    """Keeps cases that cite the given POCA section (e.g. 's327'), exact match."""
    section = section.strip().lower()
    return [c for c in cases if any(s.lower() == section for s in c.get("poca_sections", []))]


# ── Main Runtime Entry Point ──────────────────────────────────────────────────

def main():
    """
    Interactive CLI entry point: pick which output JSON file(s) to load,
    optionally narrow them down with the search/AML/POCA filters above, then
    loop letting the user select one case at a time to render in full via
    display_full_case() until they quit with 'q'.
    """
    # Target the 'outputs' directory and recursively find all .json files inside its subfolders
    outputs_dir = Path("outputs/")
    json_files = sorted(list(outputs_dir.rglob("*.json")))

    if not json_files:
        console.print("[red]No target JSON files found inside the 'outputs' folder or its subfolders.[/red]")
        return

    console.print("\n[bold cyan]Available Case Files Found:[/bold cyan]")
    for i, f in enumerate(json_files, 1):
        # Displays the path relative to 'outputs' (e.g., "subfolder/case.json")
        console.print(f"  [cyan]{i}[/cyan]  {f.relative_to(outputs_dir)}")

    choice = input("\nSelect files (comma-separated numbers, blank = evaluate all): ").strip()

    if choice == "":
        selected_files = json_files
    else:
        try:
            idxs           = [int(x.strip()) - 1 for x in choice.split(",")]
            selected_files = [json_files[i] for i in idxs if 0 <= i < len(json_files)]
        except ValueError:
            console.print("[red]Invalid numerical matrix coordinates provided.[/red]")
            return

    all_cases = []
    for f in selected_files:
        try:
            all_cases.extend(load_case_data(f))
        except Exception as e:
            console.print(f"[red]Error reading {f.name}: {e}[/red]")

    if not all_cases:
        console.print("[red]No valid structured data instances collected.[/red]")
        return

    # Filter Options
    search_term = input("\nFilter Text Search (Case name / references, blank = Skip): ").strip()
    if search_term:
        all_cases = search_cases(all_cases, search_term)

    aml_filter = input("Filter AML Status (Confirmed Verdict / Precedent Only, blank = Skip): ").strip()
    if aml_filter:
        all_cases = filter_by_aml(all_cases, aml_filter)

    poca_filter = input("Filter by POCA Section (e.g. s327, blank = Skip): ").strip()
    if poca_filter:
        all_cases = filter_by_poca(all_cases, poca_filter)

    if not all_cases:
        console.print("[yellow]Zero records match active logical criteria sets.[/yellow]")
        return

    # Master Presentation Loop
    while True:
        console.rule("[bold blue]AML CASE INTELLIGENCE CONSOLE[/bold blue]")
        console.print(f"\n[green]{len(all_cases)} case(s) loaded into visualization matrix[/green]\n")

        for i, c in enumerate(all_cases, 1):
            status    = c.get("aml_status", "—")
            ref       = c.get("case_reference", "—")
            def_count = c.get("defendant_count", 0)
            console.print(f"  [cyan]{i}[/cyan]  {ref:<25} [{aml_style(status)}]{status:<16}[/] [dim]({def_count} parties involved)[/dim]")

        console.print("  [cyan]q[/cyan]  Exit Program")
        pick = input("\nSelect index to display full table overview: ").strip().lower()

        if pick == "q":
            break

        try:
            case = all_cases[int(pick) - 1]
            # Immediately stream the clean tabular representation
            display_full_case(case)
            input("Press [Enter] to return back to the case list matrix...")
        except (ValueError, IndexError):
            console.print("[red]Selection index outside bounds of mapped array array.[/red]")


if __name__ == "__main__":
    main()