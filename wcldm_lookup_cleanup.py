"""Cleanup pass: for each flagged mismatch / zero-hit from wcldm_matched.csv,
try normalized query variants and pick the best hit across all variants.

Updates the cache (wcldm_copperknob_cache.json) with a new "variant_hits"
section per rescued dance and re-emits wcldm_matched.csv.
"""

import csv
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup

MATCHED_CSV = "wcldm_matched.csv"
PARSED_CSV = "wcldm_parsed.csv"
CACHE_PATH = "wcldm_copperknob_cache.json"
SLEEP = 0.35

SEARCH_BASE = (
    "https://www.copperknob.co.uk/search?"
    "Search={}&BeatFrom=&BeatTo=&Level=&Wall=&Lang="
)


def search(q):
    url = SEARCH_BASE.format(requests.utils.quote(q))
    try:
        resp = requests.get(url, timeout=20)
    except requests.RequestException as e:
        return {"error": str(e)[:200], "hits": []}
    bs = BeautifulSoup(resp.text, "html.parser")
    hits = []
    for item in bs.find_all("div", class_="listitem"):
        td = item.find("div", class_="listTitle")
        info = item.find("div", class_="listInfo")
        if not td: continue
        a = td.find("a")
        if not a: continue
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


_NORM = re.compile(r"[^a-z0-9]+")
def norm(s): return _NORM.sub("", s.lower())


def query_variants(name):
    """Return a de-duplicated list of alternative search queries to try."""
    vs = []
    seen = set()
    def add(q):
        q = q.strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            vs.append(q)

    add(name)                                     # original
    add(name.replace("&", "and"))                 # Delete & Repeat → Delete and Repeat
    add(name.replace("'", ""))                    # strip apostrophes
    add(re.sub(r"\bin'\b", "ing", name, flags=re.I))   # Blowin' → Blowing
    add(re.sub(r"in'(\s|$)", r"ing\1", name, flags=re.I))  # Keep Rollin' → Keep Rolling
    # Split on " / " medley separator
    for half in re.split(r"\s*/\s*", name):
        if half and half != name:
            add(half)
    # Also apply the above transforms to the halves
    for half in re.split(r"\s*/\s*", name):
        if half and half != name:
            add(half.replace("&", "and"))
            add(half.replace("'", ""))
    return vs


def score_hit(dance_name, hit_title):
    """Higher is better. 100 = exact match; title starts with name = 80;
    name is a prefix of title (case-insensitive, word-boundary) = 60;
    name is substring of title = 40; else 0.
    """
    d = norm(dance_name)
    t = norm(hit_title)
    if not d or not t:
        return 0
    if d == t: return 100
    if t.startswith(d): return 80
    if d.startswith(t): return 70  # dance name longer than title but prefix match
    if d in t: return 40
    if t in d: return 30
    return 0


def main():
    cache = json.load(open(CACHE_PATH))
    plays = {}
    with open(PARSED_CSV) as f:
        for r in csv.DictReader(f):
            plays[r["dance"]] = int(r["total_plays"])

    rows = list(csv.DictReader(open(MATCHED_CSV)))
    to_retry = [r for r in rows if r.get("note") and (
        "title mismatch" in r["note"] or r["note"] == "no matches"
    )]
    # Skip the obvious junk row
    to_retry = [r for r in to_retry if r["dance"] != "Dance Name and count"]
    print(f"Retrying {len(to_retry)} flagged dances")

    rescued = []
    for i, r in enumerate(to_retry, 1):
        name = r["dance"]
        best_score = -1
        best_hit = None
        best_query = None
        orig_hits = cache.get(name, {}).get("hits", [])
        if orig_hits:
            best_score = score_hit(name, orig_hits[0]["title"])
            best_hit = orig_hits[0]
            best_query = name  # the original
        for q in query_variants(name)[1:]:  # skip original (already in cache)
            cache_key = f"__retry__::{q}"
            if cache_key in cache:
                res = cache[cache_key]
            else:
                res = search(q)
                cache[cache_key] = res
                time.sleep(SLEEP)
            if res.get("error") or not res["hits"]:
                continue
            # Score each returned hit, pick best
            for h in res["hits"][:5]:
                s = score_hit(name, h["title"])
                if s > best_score:
                    best_score = s
                    best_hit = h
                    best_query = q
        if best_hit and best_score >= 60 and (
            not orig_hits or best_hit["url"] != orig_hits[0]["url"]
        ):
            rescued.append((name, best_query, best_hit, best_score, orig_hits[:1]))
        if i % 10 == 0:
            # Flush cache mid-run
            with open(CACHE_PATH + ".tmp", "w") as f:
                json.dump(cache, f, indent=2)
            os.replace(CACHE_PATH + ".tmp", CACHE_PATH)
            print(f"  [{i}/{len(to_retry)}] rescued so far: {len(rescued)}", flush=True)

    # Final cache save
    with open(CACHE_PATH + ".tmp", "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(CACHE_PATH + ".tmp", CACHE_PATH)

    print(f"\nRescued: {len(rescued)} dances")
    for name, q, hit, score, orig in sorted(rescued, key=lambda t: -plays.get(t[0], 0)):
        orig_t = orig[0]["title"] if orig else "(no original)"
        print(f"  {plays.get(name, 0):>3}×  {name!r}")
        print(f"        query:  {q!r}  (score={score})")
        print(f"        before: {orig_t!r}")
        print(f"        after:  {hit['title']!r} — {hit['music']!r}")
        print(f"        url:    {hit['url']}")

    # Re-emit the matched CSV with rescued rows updated
    rescued_by_name = {r[0]: r for r in rescued}
    out_rows = []
    for r in rows:
        name = r["dance"]
        if name in rescued_by_name:
            _, q, hit, score, _ = rescued_by_name[name]
            r = dict(r)
            r["matched_title"] = hit["title"]
            r["choreographer"] = hit["choreo"]
            r["music"] = hit["music"]
            r["copperknob_url"] = hit["url"]
            r["note"] = f"rescued via q={q!r}"
        out_rows.append(r)

    with open(MATCHED_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nRewrote {MATCHED_CSV} with {len(rescued)} rescued rows")

    # Final tally
    still_mismatch = sum(1 for r in out_rows if "title mismatch" in (r.get("note") or ""))
    still_zero = sum(1 for r in out_rows if r.get("note") == "no matches")
    print(f"After cleanup: title mismatches={still_mismatch}, zero-hits={still_zero}")


if __name__ == "__main__":
    main()
