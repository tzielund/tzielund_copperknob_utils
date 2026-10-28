"""Parse the WCLDM (convention dance list) Google sheet.

Column A is a location, column B is a dance name that may carry a frequency
suffix ("x3") and/or a parenthetical note ("(Aladdin)"). Aggregate across
locations so each dance has one total play-count row.

Output: wcldm_parsed.csv  (dance, total_plays, locations, notes)
"""

import csv
import re
from collections import defaultdict

from google_sheet_util import gc

SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1XOsiEAB6ifWVt4n3PH92dNpY4EXYQnw65tUTeE0FDyU/edit?gid=0#gid=0"
)
OUT_CSV = "wcldm_parsed.csv"

PAREN_RE = re.compile(r"\s*\(([^)]*)\)\s*")
# Trailing count: "x3", "X 3", "×3". Must be preceded by whitespace to avoid
# eating characters from dance names (e.g. "4x4xU" where x is part of the name).
COUNT_RE = re.compile(r"\s+[x×]\s*(\d+)\s*$", re.IGNORECASE)


def parse_cell(dance_cell: str) -> tuple[str, int, list[str]]:
    """Returns (clean_dance_name, play_count, notes_list)."""
    s = dance_cell.strip()
    notes = []
    # Pull out parentheticals first — some have trailing count AFTER them, some have it before
    while True:
        m = PAREN_RE.search(s)
        if not m:
            break
        notes.append(m.group(1).strip())
        s = (s[: m.start()] + " " + s[m.end() :]).strip()
    # Now extract trailing count
    count = 1
    m = COUNT_RE.search(s)
    if m:
        count = int(m.group(1))
        s = s[: m.start()].strip()
    return s, count, notes


# Key dances for aggregation: lowercase, apostrophes/dashes squashed
_NORM_RE = re.compile(r"[^a-z0-9]+")
def norm_key(name: str) -> str:
    return _NORM_RE.sub(" ", name.lower()).strip()


def main():
    sh = gc.open_by_url(SHEET_URL)
    ws = sh.worksheets()[0]
    rows = ws.get_all_values()
    # Skip header row
    data_rows = [r for r in rows[1:] if any(c.strip() for c in r)]
    print(f"Read {len(data_rows)} non-empty data rows")

    # dance_key -> {display: str, plays: int, locations: set, notes: set}
    agg = {}
    unparsed = 0
    for row in data_rows:
        location = row[0].strip()
        cell = row[1].strip() if len(row) > 1 else ""
        if not cell:
            continue
        name, plays, notes = parse_cell(cell)
        if not name:
            unparsed += 1
            continue
        key = norm_key(name)
        if not key:
            unparsed += 1
            continue
        bucket = agg.setdefault(key, {"display": name, "plays": 0, "locations": [], "notes": set()})
        bucket["plays"] += plays
        bucket["locations"].append(location)
        for n in notes:
            if n:
                bucket["notes"].add(n)
        # Prefer the longest display form (usually has correct capitalization/punct)
        if len(name) > len(bucket["display"]):
            bucket["display"] = name

    print(f"Unique dances: {len(agg)}")
    print(f"Unparsed rows: {unparsed}")

    # Sort by total plays desc, then name
    ranked = sorted(agg.values(), key=lambda b: (-b["plays"], b["display"].lower()))

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dance", "total_plays", "locations_count", "locations", "notes"])
        for b in ranked:
            w.writerow([
                b["display"],
                b["plays"],
                len(set(b["locations"])),
                " | ".join(sorted(set(b["locations"]))),
                " | ".join(sorted(b["notes"])),
            ])
    print(f"Wrote {OUT_CSV}")

    print("\nTop 25 most-played dances:")
    for b in ranked[:25]:
        print(f"  {b['plays']:>3}×  {b['display']}")

    print("\nSample tail (dances played once):")
    once = [b for b in ranked if b["plays"] == 1]
    print(f"  {len(once)} dances played only once")

    # Flag likely-duplicate normalizations (same key, multiple display forms)
    # (These would already be merged but let's surface the variants we chose)
    print("\n10 random merged variants (same dance, multiple spellings):")
    import random
    random.seed(0)
    sample = random.sample(list(agg.values()), min(10, len(agg)))
    # Actually, better to re-scan: find keys where any raw cell differs from display
    # (handled during aggregation — we only kept the "longest display" so just
    # show those)
    # Minor diagnostic; skip the random for now
    print("  (variants merged by lowercased, punctuation-stripped key)")


if __name__ == "__main__":
    main()
