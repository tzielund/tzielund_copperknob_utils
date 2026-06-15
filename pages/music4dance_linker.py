import re
import json
import time
import requests
import streamlit as st
import streamlit.components.v1 as components
import google_sheet_util
from google_sheet_util import read_google_sheet, read_google_sheet_as_worksheet

SEARCH_BASE = "https://www.music4dance.net/song/filterSearch?filter=v2-advanced---"
DETAIL_BASE = "https://www.music4dance.net/song/details/"
AUGMENT_URL = "https://www.music4dance.net/song/augment"

st.set_page_config(page_title="Music4Dance Linker", layout="wide")
st.title("Music4Dance Linker")


def spotify_id_from_url(spotify_url):
    m = re.search(r"/track/([A-Za-z0-9]+)", spotify_url)
    return m.group(1) if m else None


def copy_and_open_button(label, copy_text, open_url, key):
    """Render a JS button that copies copy_text to clipboard and opens open_url."""
    safe_text = copy_text.replace("'", "\\'")
    safe_url = open_url.replace("'", "\\'")
    components.html(
        f"""
        <button onclick="navigator.clipboard.writeText('{safe_text}')
                         .then(() => window.open('{safe_url}', '_blank'))"
                style="background:#4CAF50;color:white;border:none;padding:6px 14px;
                       border-radius:4px;cursor:pointer;font-size:14px;">
            {label}
        </button>
        """,
        height=42,
    )


def get_prop(history, name):
    for p in history.get("properties", []):
        if p["name"] == name:
            return p.get("value", "")
    return ""


def get_dance_tags(history):
    tags = []
    for p in history.get("properties", []):
        if p["name"] == "Tag+" and ":Dance" in p.get("value", ""):
            tags.append(p["value"].replace(":Dance", ""))
    return tags


def search_music4dance(song_title, artist):
    query = (song_title + "+" + artist).replace(" ", "+")
    url = SEARCH_BASE + query
    try:
        resp = requests.get(url, timeout=10)
        m = re.search(r"var model_\s*=\s*(\{.*?\});", resp.text, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(1))
        return data.get("histories", [])
    except Exception as e:
        st.error(f"Search failed: {e}")
        return []


def p_status(val):
    if val.startswith("http"):
        return "found"
    if val.strip().lower() in ("none", "'none'", ""):
        return "none" if val.strip().lower() == "none" else "unresolved"
    return "unresolved"


@st.cache_data(ttl=120)
def load_sheet(spreadsheet_url, sheet_name):
    df = read_google_sheet(spreadsheet_url, sheet_name)
    rows = []
    for i in range(len(df)):
        row = df.iloc[i]
        dance = str(row[0])
        song = str(row[5])
        artist = str(row[6])
        spotify = str(row[8])
        p_val = str(row[15])
        status = p_status(p_val)
        rows.append({
            "sheet_row": i + 1,  # 1-indexed for gspread
            "dance": dance,
            "song": song,
            "artist": artist,
            "spotify": spotify,
            "p_url": p_val,
            "status": status,
        })
    return rows


active_url, active_sheet_name = google_sheet_util.render_sheet_selector_sidebar()

if st.sidebar.button("Refresh sheet data"):
    load_sheet.clear()
    st.rerun()


def save_p_url(sheet_row, url):
    ws = read_google_sheet_as_worksheet()
    ws.update_cell(sheet_row, 16, url)  # col P = column 16


rows = load_sheet(active_url, active_sheet_name)

found = [r for r in rows if r["status"] == "found"]
not_found = [r for r in rows if r["status"] == "none"]
unresolved = [r for r in rows if r["status"] == "unresolved"]

col1, col2, col3 = st.columns(3)
col1.metric("Linked to Music4Dance", len(found))
col2.metric("Confirmed not found", len(not_found))
col3.metric("Not yet checked", len(unresolved))

st.divider()
tab_scan, tab_contribute, tab_found = st.tabs(["Find Matches", "Contribute Missing Songs", "Already Linked"])

# ── Tab 1: scan unresolved songs ──────────────────────────────────────────────
with tab_scan:
    if not unresolved:
        st.success("All songs have been checked!")
    else:
        song_labels = [
            f"{r['dance']} — {r['song']} by {r['artist']}" for r in unresolved
        ]
        selected_label = st.selectbox("Pick a song to look up:", song_labels)
        selected = unresolved[song_labels.index(selected_label)]

        st.markdown(
            f"**Dance:** {selected['dance']}  \n"
            f"**Song:** {selected['song']}  \n"
            f"**Artist:** {selected['artist']}  \n"
            + (f"**Spotify:** [{selected['spotify']}]({selected['spotify']})" if selected["spotify"].startswith("http") else "")
        )

        if st.button("Search Music4Dance"):
            with st.spinner("Searching…"):
                results = search_music4dance(selected["song"], selected["artist"])
            st.session_state["m4d_results"] = results
            st.session_state["m4d_song"] = selected

        results = st.session_state.get("m4d_results")
        active_song = st.session_state.get("m4d_song")

        if results is not None and active_song == selected:
            if not results:
                st.warning("No results found on Music4Dance.")
                if st.button("Mark as 'not found' in sheet"):
                    save_p_url(selected["sheet_row"], "none")
                    load_sheet.clear()
                    st.rerun()
                st.markdown(
                    f"[Contribute this song to Music4Dance ↗]({AUGMENT_URL})",
                    unsafe_allow_html=False,
                )
                st.info(
                    f"On the augment page, search for:  \n"
                    f"**Title:** {selected['song']}  \n"
                    f"**Artist:** {selected['artist']}"
                    + (f"  \n**Spotify URL:** {selected['spotify']}" if selected["spotify"].startswith("http") else "")
                )
            else:
                st.markdown(f"Found **{len(results)}** result(s). Review and pick the right one:")

                for i, h in enumerate(results[:10]):
                    title = get_prop(h, "Title")
                    artist = get_prop(h, "Artist")
                    tempo = get_prop(h, "Tempo")
                    dances = get_dance_tags(h)
                    detail_url = DETAIL_BASE + h["id"]

                    with st.expander(f"{i+1}. {title} — {artist}", expanded=(i == 0)):
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.markdown(
                                f"**Title:** {title}  \n"
                                f"**Artist:** {artist}  \n"
                                + (f"**Tempo:** {tempo} BPM  \n" if tempo else "")
                                + (f"**Dances:** {', '.join(dances)}  \n" if dances else "")
                                + f"[View on Music4Dance ↗]({detail_url})"
                            )
                        with c2:
                            if st.button("Use this one", key=f"use_{i}"):
                                save_p_url(selected["sheet_row"], detail_url)
                                load_sheet.clear()
                                st.session_state["m4d_results"] = None
                                st.success("Saved!")
                                time.sleep(0.5)
                                st.rerun()

                if len(results) > 10:
                    st.caption(f"(showing top 10 of {len(results)} results)")

                st.markdown("---")
                if st.button("None of these match — mark as not found"):
                    save_p_url(selected["sheet_row"], "none")
                    load_sheet.clear()
                    st.rerun()

# ── Tab 2: songs marked not found — contribute them ──────────────────────────
with tab_contribute:
    if not not_found:
        st.info("No songs are marked as 'not found' yet.")
    else:
        st.markdown(
            "These songs were not found on Music4Dance. Use the links below to search again "
            "or contribute them. If you find a matching page, paste its URL to save it."
        )
        for r in not_found:
            search_url = (
                SEARCH_BASE
                + (r["song"] + "+" + r["artist"]).replace(" ", "+")
            )
            with st.expander(f"{r['dance']} — {r['song']} by {r['artist']}"):
                st.markdown(
                    f"**Title:** {r['song']}  \n"
                    f"**Artist:** {r['artist']}  \n"
                    + (f"**Spotify:** {r['spotify']}  \n" if r["spotify"].startswith("http") else "")
                    + f"[Search Music4Dance ↗]({search_url})"
                )
                spotify_id = spotify_id_from_url(r["spotify"]) if r["spotify"].startswith("http") else None
                if spotify_id:
                    copy_and_open_button(
                        "Copy Spotify ID &amp; Open Contribute Page",
                        spotify_id,
                        AUGMENT_URL,
                        key=f"copy_{r['sheet_row']}",
                    )
                else:
                    st.markdown(f"[Contribute (augment) ↗]({AUGMENT_URL})")
                    current = r["spotify"]
                    st.warning(
                        f"No valid Spotify track URL — current value: `{current or '(empty)'}`.  \n"
                        "Fix it on the **Spotify Cacher** page, then come back here."
                    )
                pasted = st.text_input(
                    "Found a match? Paste the Music4Dance URL here:",
                    key=f"paste_{r['sheet_row']}",
                    placeholder="https://www.music4dance.net/song/details/...",
                )
                if st.button("Save URL", key=f"save_paste_{r['sheet_row']}"):
                    url_to_save = pasted.strip()
                    if url_to_save.startswith("http"):
                        save_p_url(r["sheet_row"], url_to_save)
                        load_sheet.clear()
                        st.success("Saved!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.warning("Please enter a valid URL first.")

# ── Tab 3: already linked ─────────────────────────────────────────────────────
with tab_found:
    if not found:
        st.info("No songs linked yet.")
    else:
        for r in found:
            st.markdown(
                f"**{r['dance']}** — {r['song']} by {r['artist']}  \n"
                f"[{r['p_url']}]({r['p_url']})"
            )
