"""Interactive curator for WCLDM dance → Copperknob URL matches.

Walks the operator through flagged rows from wcldm_matched.csv (title
mismatches, zero-hits, and anything with an open note). For each one:

- Shows the current match and current note.
- Offers an on-demand Copperknob search with a custom query (defaults to the
  dance name).
- Lets the operator pick a candidate from the search results, mark the current
  match as correct, mark the dance as un-findable, or paste a custom URL.

Edits write back to wcldm_matched.csv immediately and append each curation
decision to wcldm_curation_log.jsonl so you can audit later.
"""

import csv
import json
import os
import re
import time
from datetime import datetime

import requests
import streamlit as st
from bs4 import BeautifulSoup

MATCHED_CSV = "wcldm_matched.csv"
CACHE_PATH = "wcldm_copperknob_cache.json"
LOG_PATH = "wcldm_curation_log.jsonl"
SEARCH_BASE = (
    "https://www.copperknob.co.uk/search?"
    "Search={}&BeatFrom=&BeatTo=&Level=&Wall=&Lang="
)
COPPERKNOB_PREFIX = "https://www.copperknob.co.uk/stepsheets/"
YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com")

# Canonical column order — ensures the youtube_url column exists even if the
# source CSV predates it.
CSV_COLS = [
    "dance", "total_plays", "hits_found",
    "matched_title", "choreographer", "music",
    "copperknob_url", "youtube_url", "note",
]

st.set_page_config(page_title="WCLDM Match Curator", layout="wide")
st.title("WCLDM Match Curator")


# ─── data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else 0


def load_rows():
    with open(MATCHED_CSV) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in CSV_COLS:
            r.setdefault(c, "")
    return rows


def save_rows(rows):
    if not rows:
        return
    with open(MATCHED_CSV + ".tmp", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(MATCHED_CSV + ".tmp", MATCHED_CSV)


def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_PATH + ".tmp", "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(CACHE_PATH + ".tmp", CACHE_PATH)


def log_decision(entry):
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def search_copperknob(q):
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
            "music": (music_m.group(1).strip() if music_m else "")[:200],
        })
    return {"error": None, "hits": hits}


# ─── classification ────────────────────────────────────────────────────────────

def row_bucket(r):
    note = (r.get("note") or "").strip()
    if not note:
        return "clean"
    if note.startswith("rescued"):
        return "rescued"
    if note.startswith("confirmed") or note.startswith("manual:"):
        return "confirmed"
    if note.startswith("no match (manual)"):
        return "unmatched"
    if "title mismatch" in note:
        return "mismatch"
    if note == "no matches":
        return "zero-hit"
    if "common name" in note:
        return "common"
    return "other"


BUCKET_LABELS = {
    "mismatch":  "⚠ Title mismatch",
    "zero-hit":  "∅ Zero hits",
    "common":    "~ Common name",
    "rescued":   "✓ Rescued by cleanup",
    "confirmed": "✓ Confirmed manually",
    "unmatched": "✗ Marked as no match",
    "clean":     "✓ Clean match",
    "other":     "? Other note",
}


# ─── UI ────────────────────────────────────────────────────────────────────────

rows = load_rows()
cache = load_cache()

counts = {b: 0 for b in BUCKET_LABELS}
for r in rows:
    counts[row_bucket(r)] += 1

st.caption(f"Loaded {len(rows)} rows from `{MATCHED_CSV}` · updated "
           f"{datetime.fromtimestamp(_mtime(MATCHED_CSV)).strftime('%Y-%m-%d %H:%M')}")

bucket_cols = st.columns(len(BUCKET_LABELS))
for col, (b, label) in zip(bucket_cols, BUCKET_LABELS.items()):
    col.metric(label, counts[b])

default_buckets = [b for b in ("mismatch", "zero-hit") if counts[b]]
chosen = st.multiselect(
    "Show rows in these buckets",
    list(BUCKET_LABELS.keys()),
    default=default_buckets or ["mismatch", "zero-hit"],
    format_func=lambda b: f"{BUCKET_LABELS[b]} ({counts[b]})",
)
sort_by = st.radio("Sort by", ["plays (desc)", "dance name"], horizontal=True)

shown = [r for r in rows if row_bucket(r) in chosen]
if sort_by == "plays (desc)":
    shown.sort(key=lambda r: -int(r["total_plays"]))
else:
    shown.sort(key=lambda r: r["dance"].lower())

st.caption(f"Showing {len(shown)} rows")

# Per-row index into `rows` for in-place updates
row_index = {r["dance"]: i for i, r in enumerate(rows)}


def update_match(dance, hit, label):
    i = row_index[dance]
    rows[i]["matched_title"] = hit["title"]
    rows[i]["choreographer"] = hit["choreo"]
    rows[i]["music"]         = hit["music"]
    rows[i]["copperknob_url"] = hit["url"]
    rows[i]["hits_found"]    = rows[i].get("hits_found") or "1"
    rows[i]["note"]          = label
    save_rows(rows)
    log_decision({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "dance": dance, "action": label, "picked": hit,
    })


def confirm_current(dance):
    i = row_index[dance]
    rows[i]["note"] = "confirmed"
    save_rows(rows)
    log_decision({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "dance": dance, "action": "confirmed",
    })


def mark_unmatched(dance):
    i = row_index[dance]
    rows[i]["matched_title"] = ""
    rows[i]["choreographer"] = ""
    rows[i]["music"] = ""
    rows[i]["copperknob_url"] = ""
    rows[i]["note"] = "no match (manual)"
    save_rows(rows)
    log_decision({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "dance": dance, "action": "no match (manual)",
    })


def _is_youtube(url):
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname in YOUTUBE_HOSTS
    except Exception:
        return False


def _fetch_youtube_oembed(url):
    """Return {title, author_name, author_url} from YouTube oEmbed, or None."""
    try:
        resp = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        return None
    return None


def apply_custom_url(dance, url):
    url = url.strip()
    if not url:
        return False, "No URL supplied."
    i = row_index[dance]
    if url.startswith(COPPERKNOB_PREFIX):
        rows[i]["copperknob_url"] = url
        rows[i]["note"] = "manual: url"
        save_rows(rows)
        log_decision({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "dance": dance, "action": "manual url", "url": url,
        })
        return True, "Copperknob URL saved."
    if _is_youtube(url):
        meta = _fetch_youtube_oembed(url)
        rows[i]["youtube_url"] = url
        if meta:
            # Only overwrite title/choreo if there isn't already a Copperknob match.
            # Otherwise we'd lose the Copperknob metadata when adding YouTube as supplementary.
            if not rows[i].get("copperknob_url"):
                rows[i]["matched_title"] = meta.get("title", "") or rows[i]["matched_title"]
                rows[i]["choreographer"] = meta.get("author_name", "") or rows[i]["choreographer"]
            rows[i]["note"] = "manual: youtube"
            save_rows(rows)
            log_decision({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "dance": dance, "action": "manual youtube",
                "url": url, "title": meta.get("title"),
                "author": meta.get("author_name"),
            })
            return True, f"YouTube saved — title: {meta.get('title', '(unknown)')}"
        # oEmbed failed — still save the URL so the operator can keep moving.
        rows[i]["note"] = "manual: youtube (no metadata)"
        save_rows(rows)
        log_decision({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "dance": dance, "action": "manual youtube (no metadata)", "url": url,
        })
        return True, "YouTube URL saved (oEmbed lookup failed — title/author not populated)."
    return False, (
        "URL must be a Copperknob stepsheet or a YouTube video "
        f"(copperknob.co.uk/stepsheets/… or {', '.join(YOUTUBE_HOSTS)})."
    )


# ─── per-row cards ────────────────────────────────────────────────────────────

for r in shown[:60]:  # cap to keep the page responsive; use sort/filter to drill
    dance = r["dance"]
    bucket = row_bucket(r)
    with st.container(border=True):
        header = st.columns([5, 2])
        header[0].markdown(
            f"### {dance}  "
            f"<span style='color:#888;font-weight:400'>· "
            f"played {r['total_plays']}× · {BUCKET_LABELS[bucket]}</span>",
            unsafe_allow_html=True,
        )
        q_enc = requests.utils.quote(dance)
        q_enc_line = requests.utils.quote(f"{dance} line dance")
        header[1].markdown(
            f"[Copperknob ↗](https://www.copperknob.co.uk/search?Search={q_enc})  "
            f"· [YouTube ↗](https://www.youtube.com/results?search_query={q_enc_line})  "
            f"· [Web ↗](https://www.google.com/search?q={q_enc_line})"
        )

        has_ck = bool(r.get("copperknob_url"))
        has_yt = bool(r.get("youtube_url"))
        if has_ck or has_yt:
            links = []
            if has_ck:
                links.append(f"[Copperknob]({r['copperknob_url']})")
            if has_yt:
                links.append(f"[YouTube]({r['youtube_url']})")
            st.markdown(
                f"**Current match:** {r['matched_title']}  "
                f"· _{r['choreographer']}_  \n"
                f"🎵 {r['music']}  \n"
                + " · ".join(links)
            )
        else:
            st.markdown("_No match recorded._")

        # Search sub-form
        q_key = f"q_{dance}"
        if q_key not in st.session_state:
            st.session_state[q_key] = dance
        qcol, scol = st.columns([5, 1])
        qcol.text_input(
            "Search Copperknob with", key=q_key, label_visibility="collapsed"
        )
        if scol.button("Search", key=f"search_{dance}"):
            with st.spinner(f"Searching Copperknob for {st.session_state[q_key]!r}…"):
                res = search_copperknob(st.session_state[q_key])
                cache[f"__curator__::{st.session_state[q_key]}"] = res
                save_cache(cache)
                st.session_state[f"last_hits_{dance}"] = res.get("hits", [])
                time.sleep(0.1)
            st.rerun()

        hits = st.session_state.get(f"last_hits_{dance}")
        if hits is None:
            # Fall back to any cached hits from the earlier runs
            prior = cache.get(dance, {}).get("hits", [])
            if prior:
                hits = prior
        if hits:
            st.caption(f"{len(hits)} candidate(s):")
            for idx, h in enumerate(hits[:10]):
                pcol, labelcol = st.columns([1, 9])
                if pcol.button("Pick", key=f"pick_{dance}_{idx}"):
                    update_match(dance, h, "manual: picked")
                    st.success(f"Updated → {h['title']}")
                    st.rerun()
                labelcol.markdown(
                    f"**{h['title']}** · _{h['choreo']}_  \n"
                    f"🎵 {h['music']}  \n"
                    f"[{h['url']}]({h['url']})"
                )

        # Action buttons
        ac1, ac2, ac3, ac4 = st.columns([2, 2, 2, 4])
        if ac1.button("Current match is correct", key=f"confirm_{dance}"):
            confirm_current(dance)
            st.rerun()
        if ac2.button("No match on Copperknob", key=f"nomatch_{dance}"):
            mark_unmatched(dance)
            st.rerun()
        with ac3.popover("Paste URL (Copperknob or YouTube)"):
            url_key = f"url_{dance}"
            st.text_input(
                "URL",
                key=url_key,
                placeholder="https://www.copperknob.co.uk/stepsheets/… or https://youtu.be/…",
            )
            st.caption(
                "YouTube URLs populate title + channel name via oEmbed; use this "
                "for dances not yet on Copperknob."
            )
            if st.button("Apply URL", key=f"apply_url_{dance}"):
                ok, msg = apply_custom_url(dance, st.session_state.get(url_key, ""))
                if not ok:
                    st.error(msg)
                else:
                    st.success(msg)
                    st.rerun()

if len(shown) > 60:
    st.info(
        f"Showing first 60 of {len(shown)}. Use sort / filters above to narrow."
    )
