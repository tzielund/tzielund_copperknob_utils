import time
import requests
import streamlit as st

import spotify_streamlit_util
import spotify_util
import google_sheet_util
from google_sheet_util import read_google_sheet, read_google_sheet_as_worksheet

st.set_page_config(page_title="Spotify Cacher", layout="wide")
st.title("Spotify Cacher")

# ── Auth ──────────────────────────────────────────────────────────────────────
ignore_cached_token = st.sidebar.checkbox("Ignore cached token", False)
spotify_web_token = spotify_streamlit_util.get_cached_spotify_token(
    required=True, ignore_cache=ignore_cached_token
)
headers = spotify_streamlit_util.get_headers(spotify_web_token)


# ── Helpers ───────────────────────────────────────────────────────────────────
def is_valid_spotify_url(url):
    return str(url).startswith("https://open.spotify.com/track/")


def search_spotify(title, artist, limit=8):
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        params={"q": f"{title} {artist}", "type": "track", "limit": limit},
        headers=headers,
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("tracks", {}).get("items", [])


def fmt_duration(ms):
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def save_spotify_url(sheet_row, url):
    ws = read_google_sheet_as_worksheet()
    ws.update_cell(sheet_row, 9, url)  # col I = column 9


@st.cache_data(ttl=120)
def load_sheet(spreadsheet_url, sheet_name):
    df = read_google_sheet(spreadsheet_url, sheet_name)
    rows = []
    for i in range(len(df)):
        row = df.iloc[i]
        spotify = str(row[8])
        rows.append({
            "sheet_row": i + 1,
            "dance": str(row[0]),
            "song": str(row[5]),
            "artist": str(row[6]),
            "spotify": spotify,
            "linked": is_valid_spotify_url(spotify),
        })
    return rows


active_url, active_sheet_name = google_sheet_util.render_sheet_selector_sidebar()

if st.sidebar.button("Refresh sheet data"):
    load_sheet.clear()
    st.rerun()


@st.cache_data(ttl=300)
def load_playlist(playlist_id, ignore_cache):
    return spotify_util.cache_playlist(headers, playlist_id, {"id": playlist_id}, ignore_cache=ignore_cache)


# ── Sheet data ────────────────────────────────────────────────────────────────
rows = load_sheet(active_url, active_sheet_name)
linked = [r for r in rows if r["linked"]]
unlinked = [r for r in rows if not r["linked"]]

col1, col2 = st.columns(2)
col1.metric("Songs with Spotify URL", len(linked))
col2.metric("Songs missing Spotify URL", len(unlinked))

st.divider()
tab_find, tab_playlist = st.tabs(["Find Spotify Links", "Playlist Sync"])

# ── Tab 1: find Spotify URLs for unlinked songs ───────────────────────────────
with tab_find:
    if not unlinked:
        st.success("All songs have a Spotify URL!")
    else:
        labels = [f"{r['dance']} — {r['song']} by {r['artist']}" for r in unlinked]
        selected_label = st.selectbox("Pick a song to search:", labels)
        selected = unlinked[labels.index(selected_label)]

        current = selected["spotify"]
        if current and current not in ("", "???"):
            st.caption(f"Current value: `{current}`")

        if st.button("Search Spotify"):
            with st.spinner("Searching…"):
                results = search_spotify(selected["song"], selected["artist"])
            st.session_state["sp_results"] = results
            st.session_state["sp_song"] = selected

        results = st.session_state.get("sp_results")
        active = st.session_state.get("sp_song")

        if results is not None and active == selected:
            if not results:
                st.warning("No results found on Spotify.")
            else:
                st.markdown(f"Found **{len(results)}** result(s):")
                for i, track in enumerate(results):
                    name = track["name"]
                    artist = track["artists"][0]["name"]
                    album = track["album"]["name"]
                    duration = fmt_duration(track["duration_ms"])
                    url = track["external_urls"]["spotify"]

                    with st.expander(f"{i+1}. {name} — {artist}", expanded=(i == 0)):
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.markdown(
                                f"**Artist:** {artist}  \n"
                                f"**Album:** {album}  \n"
                                f"**Duration:** {duration}  \n"
                                f"[Open in Spotify ↗]({url})"
                            )
                        with c2:
                            if st.button("Use this one", key=f"use_{i}"):
                                save_spotify_url(selected["sheet_row"], url)
                                load_sheet.clear()
                                st.session_state["sp_results"] = None
                                st.success("Saved!")
                                time.sleep(0.5)
                                st.rerun()

# ── Tab 2: playlist sync ──────────────────────────────────────────────────────
with tab_playlist:
    playlists = spotify_util.get_cached_playlist_list(headers)
    playlist = next((p for p in playlists if p["name"] == "Zizis line dance"), None)
    practice_playlist = next((p for p in playlists if p["name"] == "Practice Playlist"), None)

    if not playlist:
        st.error("Could not find 'Zizis line dance' playlist.")
        st.stop()

    ignore_cache = st.button("Refresh playlist cache")

    playlist_data = spotify_util.cache_playlist(
        headers, playlist["id"], playlist, ignore_cache=ignore_cache
    )

    # Index sheet songs by normalised name
    sheet_index = {}
    for r in rows:
        norm = r["song"].lower().replace(" ", "")
        sheet_index[norm] = r

    # Index playlist tracks by normalised name
    playlist_index = {}
    for trackid, track in playlist_data.items():
        norm = track["name"].lower().replace(" ", "")
        playlist_index[norm] = (trackid, track)

    in_sheet_not_playlist = [
        r for norm, r in sheet_index.items() if norm not in playlist_index
    ]
    in_playlist_not_sheet = [
        track for norm, (tid, track) in playlist_index.items() if norm not in sheet_index
    ]

    left, right = st.columns(2)

    with left:
        st.subheader(f"In sheet, not playlist ({len(in_sheet_not_playlist)})")
        auto_add = {r["song"]: r["spotify"] for r in in_sheet_not_playlist if r["linked"]}
        no_url = [r for r in in_sheet_not_playlist if not r["linked"]]

        if auto_add:
            if st.button(f"Add {len(auto_add)} known songs to playlist"):
                track_ids = [url.split("/")[-1].split("?")[0] for url in auto_add.values()]
                spotify_util.add_to_playlist(headers, playlist["id"], track_ids)
                st.success("Songs added!")
            for song, url in auto_add.items():
                st.markdown(f"- [{song}]({url})")

        if no_url:
            st.markdown("**No Spotify URL (use Find tab first):**")
            for r in no_url:
                st.markdown(f"- {r['song']} by {r['artist']}")

    with right:
        st.subheader(f"In playlist, not sheet ({len(in_playlist_not_sheet)})")
        for track in in_playlist_not_sheet:
            url = track.get("external_urls", {}).get("spotify", "")
            name = track["name"]
            artist = track["artists"][0]["name"] if track.get("artists") else ""
            if url:
                st.markdown(f"- [{name} — {artist}]({url})")
            else:
                st.markdown(f"- {name} — {artist}")
