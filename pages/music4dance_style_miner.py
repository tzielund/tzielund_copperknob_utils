"""Mine dance-style votes from a music4dance.net detail URL and write them back to the sheet."""

import hashlib
import json
import os
import re
import time
from collections import Counter

import requests
import streamlit as st

from google_sheet_util import read_google_sheet, read_google_sheet_as_worksheet

M4D_CACHE_DIR = "m4d_cache/"
M4D_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 1 week

# 0-indexed positions in the DataFrame view
COL_DANCE_NAME = 0
COL_SONG = 5
COL_ARTIST = 6
COL_M4D_LINK = 15
COL_M4D_STYLE_1 = 16
COL_M4D_STYLES = 17

st.set_page_config(page_title="Music4Dance Style Miner", layout="wide")
st.title("Music4Dance Style Miner")


@st.cache_data(ttl=600)
def load_sheet():
    df = read_google_sheet()
    rows = []
    for i in range(len(df)):
        r = df.iloc[i]
        rows.append({
            "sheet_row": i + 1,  # 1-indexed for gspread
            "dance": str(r[COL_DANCE_NAME]),
            "song": str(r[COL_SONG]),
            "artist": str(r[COL_ARTIST]),
            "m4d_url": str(r[COL_M4D_LINK]).strip(),
            "current_top": str(r[COL_M4D_STYLE_1]).strip(),
            "current_list": str(r[COL_M4D_STYLES]).strip(),
        })
    return rows


def _cache_path(url):
    os.makedirs(M4D_CACHE_DIR, exist_ok=True)
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return os.path.join(M4D_CACHE_DIR, f"{h}.html")


def fetch_m4d_page(url):
    """Return (html, cached_age_seconds_or_None). Uses on-disk cache fresh for one week."""
    path = _cache_path(url)
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < M4D_CACHE_TTL_SECONDS:
            with open(path) as f:
                return f.read(), age
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    with open(path, "w") as f:
        f.write(resp.text)
    return resp.text, None


def parse_dance_votes(html):
    """Return a list of (dance_name, net_votes) sorted by votes descending.

    Walks the Tag+/Tag- entries in `var model_`, counts pipe-separated values ending in ':Dance'.
    """
    m = re.search(r"var model_\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not m:
        return []
    data = json.loads(m.group(1))
    props = data.get("songHistory", {}).get("properties", [])
    counts = Counter()
    for p in props:
        sign = {"Tag+": 1, "Tag-": -1}.get(p.get("name"))
        if sign is None:
            continue
        for piece in (p.get("value") or "").split("|"):
            piece = piece.strip()
            if piece.endswith(":Dance"):
                counts[piece[: -len(":Dance")]] += sign
    return [(d, n) for d, n in counts.most_common() if n != 0]


def save_to_sheet(sheet_row, top_style, styles_list):
    ws = read_google_sheet_as_worksheet()
    # gspread is 1-indexed for both row and column
    ws.update_cell(sheet_row, COL_M4D_STYLE_1 + 1, top_style)
    ws.update_cell(sheet_row, COL_M4D_STYLES + 1, styles_list)


if st.sidebar.button("Refresh sheet data"):
    load_sheet.clear()
    st.rerun()

rows = load_sheet()
linked_rows = [r for r in rows if r["m4d_url"].startswith("http")]
st.caption(f"{len(linked_rows)} of {len(rows)} rows have a Music4Dance link")

show_only_unmined = st.checkbox("Only show songs without a mined top style", value=True)
candidates = [r for r in linked_rows if not r["current_top"]] if show_only_unmined else linked_rows

if not candidates:
    st.success("Nothing to mine — every linked song already has a top style.")
    st.stop()

labels = [f"{r['dance']} — {r['song']} by {r['artist']}" for r in candidates]
selected_label = st.selectbox("Pick a song:", labels)
selected = candidates[labels.index(selected_label)]

st.markdown(
    f"**Song:** {selected['song']}  \n"
    f"**Artist:** {selected['artist']}  \n"
    f"**M4D link:** [{selected['m4d_url']}]({selected['m4d_url']})  \n"
    f"**Current top style in sheet:** {selected['current_top'] or '*(empty)*'}  \n"
    f"**Current style list in sheet:** {selected['current_list'] or '*(empty)*'}"
)

if st.button("Mine dance styles"):
    with st.spinner("Loading music4dance page..."):
        try:
            html, cached_age = fetch_m4d_page(selected["m4d_url"])
            votes = parse_dance_votes(html)
        except Exception as e:
            st.error(f"Fetch/parse failed: {e}")
            votes = None
            cached_age = None
    st.session_state["m4d_votes"] = votes
    st.session_state["m4d_song_row"] = selected["sheet_row"]
    st.session_state["m4d_cached_age"] = cached_age

votes = st.session_state.get("m4d_votes")
if votes is not None and st.session_state.get("m4d_song_row") == selected["sheet_row"]:
    cached_age = st.session_state.get("m4d_cached_age")
    if cached_age is None:
        st.caption("Fetched fresh from music4dance.net (saved to cache).")
    else:
        days = cached_age / 86400
        st.caption(f"Loaded from cache ({days:.1f} days old). Delete the cache file to force re-fetch.")
    if not votes:
        st.warning("No dance-tag votes found on this page.")
    else:
        top_style = votes[0][0]
        styles_list = ", ".join(f"{d} ({n})" for d, n in votes)
        st.markdown(f"**Top style:** {top_style}")
        st.markdown(f"**Styles:** {styles_list}")
        if st.button("Save to sheet"):
            save_to_sheet(selected["sheet_row"], top_style, styles_list)
            load_sheet.clear()
            st.session_state["m4d_votes"] = None
            st.success("Saved.")
            time.sleep(0.5)
            st.rerun()
