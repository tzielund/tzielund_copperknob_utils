"""Look up each parsed WCLDM dance on Copperknob and record the top hit.

Reads   : wcldm_parsed.csv
Caches  : wcldm_copperknob_cache.json   (one entry per dance name; re-run skips)
Writes  : wcldm_matched.csv             (dance, plays, matched title, choreo,
                                         music, url, hit_count, note)

Rate-respectful: 0.35s sleep between HTTP calls, cache saved every 25 lookups.
"""

import csv
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

PARSED_CSV = "wcldm_parsed.csv"
CACHE_PATH = "wcldm_copperknob_cache.json"
OUT_CSV = "wcldm_matched.csv"
SLEEP = 0.35
SAVE_EVERY = 25

SEARCH_BASE = (
    "https://www.copperknob.co.uk/search?"
    "Search={}&BeatFrom=&BeatTo=&Level=&Wall=&Lang="
)


def search_copperknob(title):
    url = SEARCH_BASE.format(requests.utils.quote(title))
    try:
        resp = requests.get(url, timeout=20)
    except requests.RequestException as e:
        return {"error": str(e)[:200], "hits": []}
    bs = BeautifulSoup(resp.text, "html.parser")
    hits = []
    for item in bs.find_all("div", class_="listitem"):
        td = item.find("div", class_="listTitle")
        info = item.find("div", class_="listInfo")
        if not td:
            continue
        a = td.find("a")
        if not a:
            continue
        choreo_span = td.find("span", class_="listTitleColor2")
        info_text = info.text if info else ""
        music_m = re.search(r"Music:\s*(.+)", info_text)
        hits.append({
            "url": a["href"],
            "title": a.text.strip(),
            "choreo": choreo_span.text.strip() if choreo_span else "",
            "music": (music_m.group(1).strip() if music_m else "")[:140],
        })
    return {"error": None, "hits": hits}


def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, CACHE_PATH)


def main():
    with open(PARSED_CSV) as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded {len(rows)} parsed dances")

    cache = load_cache()
    print(f"Cache has {len(cache)} prior lookups")

    # Deterministic order: highest-play dances first
    rows.sort(key=lambda r: -int(r["total_plays"]))

    looked_up_this_run = 0
    for i, r in enumerate(rows, 1):
        name = r["dance"]
        if name in cache:
            continue
        result = search_copperknob(name)
        cache[name] = result
        looked_up_this_run += 1
        if looked_up_this_run % 25 == 0:
            save_cache(cache)
            print(f"  [{i}/{len(rows)}] cached {looked_up_this_run} new; last: {name!r} "
                  f"→ {len(result['hits'])} hits", flush=True)
        time.sleep(SLEEP)

    save_cache(cache)
    print(f"Lookup pass done. Cached {len(cache)} total; {looked_up_this_run} new this run.")

    # Emit a flat CSV joining cache hits with play counts
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "dance", "total_plays", "hits_found",
            "matched_title", "choreographer", "music", "copperknob_url", "note",
        ])
        no_hit = 0
        for r in rows:
            name = r["dance"]
            plays = int(r["total_plays"])
            cached = cache.get(name, {"hits": [], "error": "missing"})
            if cached.get("error"):
                w.writerow([name, plays, 0, "", "", "", "", f"ERROR: {cached['error']}"])
                continue
            hits = cached.get("hits", [])
            if not hits:
                no_hit += 1
                w.writerow([name, plays, 0, "", "", "", "", "no matches"])
                continue
            top = hits[0]
            # Flag ambiguous title match (dance name differs substantially from hit title)
            dn = re.sub(r"[^a-z0-9]+", "", name.lower())
            tn = re.sub(r"[^a-z0-9]+", "", top["title"].lower())
            note = ""
            if dn and tn and dn not in tn and tn not in dn:
                note = "⚠ title mismatch — review"
            if len(hits) > 10:
                note = (note + " · " if note else "") + f"common name ({len(hits)} hits)"
            w.writerow([
                name, plays, len(hits),
                top["title"], top["choreo"], top["music"], top["url"], note,
            ])

    print(f"Wrote {OUT_CSV}")
    print(f"  Dances with zero hits: {no_hit}")


if __name__ == "__main__":
    sys.exit(main())
