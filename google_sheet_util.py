import gspread
import pandas

gc = gspread.service_account(filename="book-bingo-gbapi-d6b744a8292f.json")

# The Line Dance Origins workbook + worksheet are the default for all pages.
# Pages that want to point at a different sheet can either pass overrides directly
# or call render_sheet_selector_sidebar() to let the user pick at runtime.
DEFAULT_SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1ZoPjRSl1K43XZY77ThkV-qZwzzMWYl3HY__4KhnZuYs/edit?usp=sharing"
)
DEFAULT_SHEET_NAME = "Line Dance Origins"


def get_active_selection():
    """Return (spreadsheet_url, sheet_name) from Streamlit session_state, else defaults.

    Safe to call outside Streamlit (e.g. from scripts) — returns the defaults if streamlit
    or session_state aren't available.
    """
    try:
        import streamlit as st
        url = st.session_state.get("active_spreadsheet_url", DEFAULT_SPREADSHEET_URL)
        sheet_name = st.session_state.get("active_sheet_name", DEFAULT_SHEET_NAME)
    except Exception:
        url = DEFAULT_SPREADSHEET_URL
        sheet_name = DEFAULT_SHEET_NAME
    return url, sheet_name


def _resolve_worksheet(sh, sheet_name):
    """Look up a worksheet by name. Fall back to the first worksheet if name isn't present."""
    try:
        return sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return sh.get_worksheet(0)


def read_google_sheet(spreadsheet_url=None, sheet_name=None):
    if spreadsheet_url is None or sheet_name is None:
        active_url, active_sheet = get_active_selection()
        spreadsheet_url = spreadsheet_url or active_url
        sheet_name = sheet_name or active_sheet
    sh = gc.open_by_url(spreadsheet_url)
    worksheet = _resolve_worksheet(sh, sheet_name)
    data = worksheet.get_all_values()
    return pandas.DataFrame(data)


def read_google_sheet_as_worksheet(spreadsheet_url=None, sheet_name=None):
    if spreadsheet_url is None or sheet_name is None:
        active_url, active_sheet = get_active_selection()
        spreadsheet_url = spreadsheet_url or active_url
        sheet_name = sheet_name or active_sheet
    sh = gc.open_by_url(spreadsheet_url)
    return _resolve_worksheet(sh, sheet_name)


def render_sheet_selector_sidebar():
    """Render a sidebar selector for the active spreadsheet and worksheet.

    Returns the active (spreadsheet_url, sheet_name) — both also live in
    st.session_state under "active_spreadsheet_url" and "active_sheet_name", so callers
    that just want to react to the selection can read those keys directly.

    Pass the returned values into cache_data-wrapped load functions so the cache
    invalidates when the selection changes.
    """
    import streamlit as st

    with st.sidebar:
        st.markdown("**Sheet selection**")
        st.text_input(
            "Spreadsheet URL",
            value=st.session_state.get("active_spreadsheet_url", DEFAULT_SPREADSHEET_URL),
            key="active_spreadsheet_url",
            help="Defaults to the Line Dance Origins workbook.",
        )
        url = st.session_state["active_spreadsheet_url"]
        try:
            sh = gc.open_by_url(url)
            titles = [ws.title for ws in sh.worksheets()]
        except Exception as e:
            st.warning(f"Couldn't list worksheets: {e}")
            titles = [DEFAULT_SHEET_NAME]
        current = st.session_state.get("active_sheet_name", DEFAULT_SHEET_NAME)
        if current not in titles:
            current = titles[0] if titles else DEFAULT_SHEET_NAME
        st.selectbox(
            "Worksheet",
            titles,
            index=titles.index(current) if current in titles else 0,
            key="active_sheet_name",
        )
    return st.session_state["active_spreadsheet_url"], st.session_state["active_sheet_name"]


def get_song_list_selector(sheet):
    # Return a displayable list of songs mapped to their spotify urls
    song_list = sheet[[5, 6]]
    song_list = song_list.apply(lambda x: f"{x[5]} by {x[6]}", axis=1).tolist()
    spotify_list = sheet[8].tolist()
    song_dict = dict(zip(song_list, spotify_list))
    return song_dict


def update_copperknob_url_at(df_row_index, new_url, url_column_index=7):
    """Update the URL column of a known row. df_row_index is 0-based from the DataFrame;
    gspread is 1-based for both row and column.
    """
    worksheet = read_google_sheet_as_worksheet()
    worksheet.update_cell(df_row_index + 1, url_column_index + 1, new_url)
    return f"Updated row {df_row_index + 1} -> {new_url}"


def add_dance_to_sheet(sheet, dance_name, choreographer, count, walls, level, song_name, song_artist, spotify_url):
    new_row = {
        0: dance_name,
        1: choreographer,
        2: count,
        3: walls,
        4: level,
        5: song_name,
        6: song_artist,
        7: spotify_url
    }
    worksheet = read_google_sheet_as_worksheet()
    worksheet.append_row(list(new_row.values()))
    return "Dance added to sheet."
