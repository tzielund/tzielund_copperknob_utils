"""Backfill the sheet from m4d_pattern_dances.csv: recover m4d URLs and fill in dance styles."""

import re
from collections import Counter

import pandas as pd
import streamlit as st

from google_sheet_util import read_google_sheet, read_google_sheet_as_worksheet

PATTERN_CSV_PATH = "m4d_pattern_dances.csv"

# 0-indexed positions in the DataFrame view of the sheet
COL_DANCE_NAME = 0
COL_SONG = 5
COL_ARTIST = 6
COL_SPOTIFY = 8
COL_M4D_LINK = 15
COL_M4D_STYLE_1 = 16
COL_M4D_STYLES = 17

st.set_page_config(page_title="M4D Pattern Backfill", layout="wide")
st.title("M4D Pattern Backfill")


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


@st.cache_data(ttl=600)
def load_sheet():
    df = read_google_sheet()
    out = []
    for i in range(len(df)):
        r = df.iloc[i]
        out.append({
            "sheet_row": i + 1,
            "dance": str(r[COL_DANCE_NAME]),
            "song": str(r[COL_SONG]),
            "artist": str(r[COL_ARTIST]),
            "spotify": str(r[COL_SPOTIFY]).strip(),
            "m4d_url": str(r[COL_M4D_LINK]).strip(),
            "style_1": str(r[COL_M4D_STYLE_1]).strip(),
            "styles": str(r[COL_M4D_STYLES]).strip(),
        })
    return out


@st.cache_data(ttl=3600)
def load_pattern_csv():
    """Read the UTF-16 CSV, group by SongId, and return a list of per-song aggregates."""
    df = pd.read_csv(PATTERN_CSV_PATH, encoding="utf-16-le")
    songs = []
    for song_id, group in df.groupby("SongId"):
        first = group.iloc[0]
        # Build dance -> votes mapping (one row per dance per song)
        votes = Counter()
        for _, row in group.iterrows():
            dance = str(row["Dance"]).strip()
            v = row["Votes"]
            if dance and not pd.isna(v):
                votes[dance] += int(v)
        ordered = [(d, n) for d, n in votes.most_common() if n != 0]
        songs.append({
            "song_id": song_id,
            "title": str(first["Title"]).strip(),
            "artist": str(first["Artist"]).strip(),
            "spotify": str(first.get("Spotify", "")).strip(),
            "m4d_url": str(first.get("music4dance", "")).strip(),
            "votes": ordered,
            "top_style": ordered[0][0] if ordered else "",
            "styles_list": ", ".join(f"{d} ({n})" for d, n in ordered),
        })
    return songs


def build_indexes(songs):
    """Build lookup indexes: by normalized spotify track ID and by normalized title+artist."""
    by_spotify = {}
    by_title_artist = {}
    for s in songs:
        sp = s["spotify"]
        if sp.startswith("http"):
            tid = sp.rstrip("/").split("/")[-1].split("?")[0]
            by_spotify[tid] = s
        key = (_norm(s["title"]), _norm(s["artist"]))
        if all(key):
            by_title_artist[key] = s
    return by_spotify, by_title_artist


def match_row(row, by_spotify, by_title_artist):
    """Return (matched_song_or_None, match_method)."""
    if row["spotify"].startswith("http"):
        tid = row["spotify"].rstrip("/").split("/")[-1].split("?")[0]
        if tid in by_spotify:
            return by_spotify[tid], "spotify"
    key = (_norm(row["song"]), _norm(row["artist"]))
    if all(key) and key in by_title_artist:
        return by_title_artist[key], "title+artist"
    return None, None


def write_cells(sheet_row, **updates):
    """updates: keyword args mapping column-name -> value. Writes one cell per update."""
    col_map = {
        "m4d_url": COL_M4D_LINK + 1,
        "style_1": COL_M4D_STYLE_1 + 1,
        "styles": COL_M4D_STYLES + 1,
    }
    ws = read_google_sheet_as_worksheet()
    for key, value in updates.items():
        ws.update_cell(sheet_row, col_map[key], value)


if st.sidebar.button("Refresh sheet data"):
    load_sheet.clear()
    st.rerun()

sheet_rows = load_sheet()
songs = load_pattern_csv()
by_spotify, by_title_artist = build_indexes(songs)

st.caption(f"Loaded {len(sheet_rows)} sheet rows and {len(songs)} songs from {PATTERN_CSV_PATH}")

# Classify sheet rows by what would change
recover_url = []      # sheet m4d_url == "none" or empty, CSV has URL
fill_styles = []      # sheet style_1 empty, CSV has style
already_set = []      # both sides have values
unmatched = []        # no CSV match

for row in sheet_rows:
    match, method = match_row(row, by_spotify, by_title_artist)
    if not match:
        if row["song"] and row["song"].lower() != "song name":  # skip header row
            unmatched.append(row)
        continue
    needs_url = not row["m4d_url"].startswith("http") and match["m4d_url"].startswith("http")
    needs_styles = not row["style_1"] and match["top_style"]
    record = {"sheet": row, "csv": match, "method": method}
    if needs_url:
        recover_url.append(record)
    elif needs_styles:
        fill_styles.append(record)
    else:
        already_set.append(record)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Recover URL", len(recover_url))
c2.metric("Fill styles", len(fill_styles))
c3.metric("Already set", len(already_set))
c4.metric("Unmatched", len(unmatched))

st.divider()
tab_url, tab_styles, tab_done, tab_unmatched = st.tabs([
    f"Recover URLs ({len(recover_url)})",
    f"Fill styles ({len(fill_styles)})",
    f"Already set ({len(already_set)})",
    f"Unmatched ({len(unmatched)})",
])


def render_proposed_change(record, container, key_prefix):
    row, match, method = record["sheet"], record["csv"], record["method"]
    container.markdown(
        f"**{row['dance']}** — {row['song']} by {row['artist']}  \n"
        f"Match method: `{method}`  \n"
        f"Current m4d URL: `{row['m4d_url'] or '(empty)'}`  \n"
        f"Current top style: `{row['style_1'] or '(empty)'}`  \n"
        f"Proposed m4d URL: `{match['m4d_url']}`  \n"
        f"Proposed top style: `{match['top_style']}`  \n"
        f"Proposed styles list: `{match['styles_list']}`"
    )
    if container.button("Apply", key=f"{key_prefix}_{row['sheet_row']}"):
        updates = {}
        if not row["m4d_url"].startswith("http"):
            updates["m4d_url"] = match["m4d_url"]
        if not row["style_1"]:
            updates["style_1"] = match["top_style"]
        if not row["styles"]:
            updates["styles"] = match["styles_list"]
        write_cells(row["sheet_row"], **updates)
        load_sheet.clear()
        container.success(f"Applied: {', '.join(updates) or '(no changes)'}")


with tab_url:
    if not recover_url:
        st.info("Nothing to recover.")
    else:
        if st.button("Apply all (recover URLs)", key="apply_all_url"):
            for r in recover_url:
                updates = {
                    "m4d_url": r["csv"]["m4d_url"],
                    "style_1": r["csv"]["top_style"],
                    "styles": r["csv"]["styles_list"],
                }
                write_cells(r["sheet"]["sheet_row"], **updates)
            load_sheet.clear()
            st.success(f"Updated {len(recover_url)} rows.")
            st.rerun()
        for r in recover_url:
            with st.expander(f"{r['sheet']['song']} by {r['sheet']['artist']} — proposes URL + styles"):
                render_proposed_change(r, st, "url")

with tab_styles:
    if not fill_styles:
        st.info("Nothing to fill in.")
    else:
        if st.button("Apply all (fill styles)", key="apply_all_styles"):
            for r in fill_styles:
                updates = {
                    "style_1": r["csv"]["top_style"],
                    "styles": r["csv"]["styles_list"],
                }
                write_cells(r["sheet"]["sheet_row"], **updates)
            load_sheet.clear()
            st.success(f"Updated {len(fill_styles)} rows.")
            st.rerun()
        for r in fill_styles:
            with st.expander(f"{r['sheet']['song']} by {r['sheet']['artist']} — proposes styles"):
                render_proposed_change(r, st, "styles")

with tab_done:
    st.caption("Sheet already has m4d URL and top style. Showing for verification.")
    for r in already_set:
        with st.expander(f"{r['sheet']['song']} by {r['sheet']['artist']}"):
            st.markdown(
                f"Sheet top style: `{r['sheet']['style_1']}` ↔ CSV top style: `{r['csv']['top_style']}`  \n"
                f"Match method: `{r['method']}`"
            )

with tab_unmatched:
    st.caption("Sheet rows that didn't match any record in the CSV.")
    for r in unmatched:
        st.markdown(f"- **{r['dance']}** — {r['song']} by {r['artist']}")
