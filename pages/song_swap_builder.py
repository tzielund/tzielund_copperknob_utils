"""Build a "<dance> Swaps" worksheet listing alternative songs for a chosen line dance.

Flow:
1. Pick a dance — either from a row in the source sheet or by pasting a Copperknob URL.
2. Create (or open) a "<dance name> Swaps" worksheet in the active workbook. On creation,
   the source sheet's header row is copied, plus the chosen dance row as the first entry.
3. Search Spotify by song title + artist (or by URL/ID) and append the chosen track as a new
   row, carrying over the dance metadata.
"""

import re

import gspread
import pandas as pd
import requests
import streamlit as st

import google_sheet_util
import spotify_streamlit_util
from google_sheet_util import gc, read_google_sheet
from stepsheet_util import Stepsheet

DANCE_NAME_COL = 0
CHOREOGRAPHER_COL = 1
COUNTS_COL = 2
WALLS_COL = 3
DIFFICULTY_COL = 4
SONG_NAME_COL = 5
ARTIST_COL = 6
COPPERKNOB_URL_COL = 7
SPOTIFY_URL_COL = 8

st.set_page_config(page_title="Song Swap Builder", layout="wide")
st.title("Song Swap Builder")

active_url, active_sheet_name = google_sheet_util.render_sheet_selector_sidebar()


@st.cache_data(ttl=300)
def load_source_sheet(spreadsheet_url, sheet_name):
    return read_google_sheet(spreadsheet_url, sheet_name)


source_df = load_source_sheet(active_url, active_sheet_name)
if source_df.empty:
    st.error("Source sheet is empty.")
    st.stop()

header_row = source_df.iloc[0].tolist()
data_rows = source_df.iloc[1:].reset_index(drop=True)


def safe_sheet_name(name, suffix=" Swaps"):
    sanitized = re.sub(r"[\\/?*\[\]:]", "", str(name)).strip() or "Untitled"
    max_len = 100 - len(suffix)
    return sanitized[:max_len] + suffix


def row_from_stepsheet(metadata, url, n_cols):
    """Build a dance row with metadata pulled from a Copperknob stepsheet."""
    music = metadata.get("music", "")
    if " - " in music:
        song_name, song_artist = (s.strip() for s in music.split(" - ", 1))
    else:
        song_name, song_artist = music.strip(), ""
    row = [""] * n_cols
    row[DANCE_NAME_COL] = metadata.get("title", "")
    row[CHOREOGRAPHER_COL] = metadata.get("choreographer", "")
    row[COUNTS_COL] = metadata.get("count", "")
    row[WALLS_COL] = metadata.get("wall", "")
    row[DIFFICULTY_COL] = metadata.get("level", "")
    row[SONG_NAME_COL] = song_name
    row[ARTIST_COL] = song_artist
    row[COPPERKNOB_URL_COL] = url
    return row


# ── Spotify auth (required for search) ────────────────────────────────
ignore_cached_token = st.sidebar.checkbox("Ignore cached Spotify token", False)
spotify_web_token = spotify_streamlit_util.get_cached_spotify_token(
    required=False, ignore_cache=ignore_cached_token
)
spotify_headers = (
    spotify_streamlit_util.get_headers(spotify_web_token) if spotify_web_token else None
)


# ── 1. Pick the dance ─────────────────────────────────────────────────
st.subheader("1. Pick a dance")
source_mode = st.radio(
    "How do you want to pick the dance?",
    ["From source sheet", "Paste Copperknob URL"],
    horizontal=True,
)

dance_name = None
dance_row_values = None

if source_mode == "From source sheet":
    options = []
    for i, row in data_rows.iterrows():
        name = str(row[DANCE_NAME_COL]).strip()
        url = str(row[COPPERKNOB_URL_COL]).strip()
        if name:
            options.append((i, name, url))
    if not options:
        st.warning("No dances found in the source sheet.")
        st.stop()
    labels = [f"{name}" + (f"  ·  {url}" if url else "") for _, name, url in options]
    chosen_label = st.selectbox("Choose a dance", labels)
    idx = labels.index(chosen_label)
    sheet_idx, dance_name, _ = options[idx]
    dance_row_values = data_rows.iloc[sheet_idx].tolist()
    if len(dance_row_values) < len(header_row):
        dance_row_values += [""] * (len(header_row) - len(dance_row_values))
else:
    cb_url = st.text_input("Copperknob URL").strip()
    if not cb_url:
        st.info("Paste a Copperknob URL to continue.")
        st.stop()
    # Prefer an existing row in source sheet if the URL matches
    matched = None
    for _, row in data_rows.iterrows():
        if str(row[COPPERKNOB_URL_COL]).strip() == cb_url:
            matched = row.tolist()
            break
    if matched:
        dance_row_values = matched
        if len(dance_row_values) < len(header_row):
            dance_row_values += [""] * (len(header_row) - len(dance_row_values))
        dance_name = dance_row_values[DANCE_NAME_COL]
        st.success(f"Found in source sheet: **{dance_name}**")
    else:
        with st.spinner("Fetching Copperknob page…"):
            stepsheet = Stepsheet(cb_url)
        if not stepsheet.is_valid:
            st.error("That URL didn't resolve to a Copperknob stepsheet.")
            st.stop()
        dance_row_values = row_from_stepsheet(stepsheet.metadata, cb_url, len(header_row))
        dance_name = dance_row_values[DANCE_NAME_COL]
        st.info(f"Inferred from Copperknob: **{dance_name}**")
        with st.expander("Parsed Copperknob metadata"):
            st.json(stepsheet.metadata)

if not dance_name:
    st.stop()


# ── 2. Create or open the swap worksheet ──────────────────────────────
swap_sheet_name = safe_sheet_name(dance_name)
st.subheader(f"2. Swap sheet: `{swap_sheet_name}`")

sh = gc.open_by_url(active_url)
try:
    swap_ws = sh.worksheet(swap_sheet_name)
    st.caption(f"Worksheet already exists in this workbook.")
except gspread.WorksheetNotFound:
    swap_ws = None
    if st.button("Create swap worksheet"):
        new_ws = sh.add_worksheet(title=swap_sheet_name, rows=200, cols=max(20, len(header_row)))
        new_ws.append_row(header_row)
        new_ws.append_row(dance_row_values)
        st.success(f"Created **{swap_sheet_name}** with header + the dance row.")
        st.rerun()
    st.info("Click the button to create the worksheet.")
    st.stop()

swap_df = pd.DataFrame(swap_ws.get_all_values())
st.dataframe(swap_df, hide_index=True)


# ── 3. Add a song ─────────────────────────────────────────────────────
st.subheader("3. Add a song")
if not spotify_headers:
    st.warning(
        "No Spotify token — Spotify search and URL lookup are disabled. "
        "Visit the Spotify Authorization page first."
    )

c1, c2 = st.columns(2)
new_song = c1.text_input("Song title", key="swap_new_song")
new_artist = c2.text_input("Artist", key="swap_new_artist")
new_spotify_url = st.text_input("Spotify URL or track ID (optional, skips search)", key="swap_new_spotify_url")


def extract_spotify_track_id(text):
    text = text.strip()
    if not text:
        return None
    if "/" in text:
        return text.rstrip("/").split("/")[-1].split("?")[0]
    return text  # assume bare ID


def fmt_track(track):
    artist_names = ", ".join(a["name"] for a in track.get("artists", []))
    album = track.get("album", {}).get("name", "")
    return f"{track.get('name', '')}  —  {artist_names}  ·  {album}"


def append_track_row(track):
    artist_names = ", ".join(a["name"] for a in track.get("artists", []))
    row = list(dance_row_values)  # copy dance metadata
    if len(row) < len(header_row):
        row += [""] * (len(header_row) - len(row))
    row[SONG_NAME_COL] = track["name"]
    row[ARTIST_COL] = artist_names
    if len(row) > SPOTIFY_URL_COL:
        row[SPOTIFY_URL_COL] = track["external_urls"]["spotify"]
    swap_ws.append_row(row)


col_a, col_b = st.columns(2)
if col_a.button("Search Spotify", disabled=not spotify_headers):
    if new_spotify_url:
        tid = extract_spotify_track_id(new_spotify_url)
        resp = requests.get(
            f"https://api.spotify.com/v1/tracks/{tid}",
            headers=spotify_headers,
            timeout=10,
        )
        if resp.status_code == 200:
            st.session_state["swap_search_results"] = [resp.json()]
        else:
            st.error(f"Lookup failed: {resp.status_code} {resp.text[:200]}")
    elif new_song or new_artist:
        q = " ".join(p for p in [new_song, new_artist] if p).strip()
        resp = requests.get(
            "https://api.spotify.com/v1/search",
            params={"q": q, "type": "track", "limit": 10},
            headers=spotify_headers,
            timeout=10,
        )
        if resp.status_code == 200:
            st.session_state["swap_search_results"] = resp.json().get("tracks", {}).get("items", [])
        else:
            st.error(f"Search failed: {resp.status_code} {resp.text[:200]}")
    else:
        st.warning("Enter a song title, artist, or Spotify URL/ID before searching.")

results = st.session_state.get("swap_search_results", [])
if results:
    labels = [fmt_track(t) for t in results]
    chosen_label = st.selectbox("Matching tracks", labels, key="swap_search_chosen")
    chosen_track = results[labels.index(chosen_label)]
    if st.button("Add selected track to swap sheet"):
        append_track_row(chosen_track)
        st.success(f"Added: {fmt_track(chosen_track)}")
        st.session_state.pop("swap_search_results", None)
        st.rerun()
