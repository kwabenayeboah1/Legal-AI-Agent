import csv

def load_sic_codes(filepath: str) -> list[dict]:
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
    return '\n'.join(f"{s['code']}: {s['description']}" for s in sic_codes)