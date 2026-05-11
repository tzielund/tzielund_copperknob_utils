# Compare the sheet to the favourites to see if there are any new dances to add to the favourites.
import re

import requests
# Read data from exported favourites file
import streamlit

from google_sheet_util import read_google_sheet, add_dance_to_sheet, update_copperknob_url_at
from local_fav_utils import read_local_favourites, local_favourites_file_in_project
from stepsheet_util import Stepsheet

local_favourites = read_local_favourites(local_favourites_file_in_project)


@streamlit.cache_data(ttl=600)
def _cached_google_sheet():
    return read_google_sheet()


google_sheet = _cached_google_sheet()

if streamlit.button("Refresh google sheet"):
    _cached_google_sheet.clear()
    streamlit.rerun()

local_copperknob_url_column = "URL"
local_title_column = "Title"
local_choreographer_column = "Choreographer"
google_sheet_copperknob_url_column = 7
google_sheet_title_column = 0
google_sheet_choreographer_column = 1


def _normalize_title(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

# Show local favourites
show_local_favourites = streamlit.checkbox("Show local favourites")
if show_local_favourites:
    streamlit.dataframe(local_favourites)

# Show google sheet
show_google_sheet = streamlit.checkbox("Show google sheet")
if show_google_sheet:
    streamlit.dataframe(google_sheet)

# Compare the data to see if there are any new dances to add either way
streamlit.header("Comparison")
left_col, rite_col = streamlit.columns(2)
left_col.header("Local Favourites unmatched")
rite_col.header("Google Sheet unmatched")

# Create a dictionary of the local favourites
local_favourites_index = dict()
for index, row in local_favourites.iterrows():
    local_favourites_index[row[local_copperknob_url_column]] = row

# Create a dictionary of the google sheet
google_sheet_index = dict()
for index, row in google_sheet.iterrows():
    google_sheet_index[row[google_sheet_copperknob_url_column]] = row

unmatched_local_urls = [u for u in local_favourites_index if u not in google_sheet_index]
unmatched_sheet_urls = [u for u in google_sheet_index if u not in local_favourites_index]

# Build normalized-title indexes scoped to unmatched items on each side
unmatched_local_by_title = {}
for u in unmatched_local_urls:
    row = local_favourites_index[u]
    norm = _normalize_title(row.get(local_title_column, ""))
    if norm:
        unmatched_local_by_title.setdefault(norm, []).append((u, row))

unmatched_sheet_by_title = {}
for u in unmatched_sheet_urls:
    row = google_sheet_index[u]
    norm = _normalize_title(row[google_sheet_title_column])
    if norm:
        unmatched_sheet_by_title.setdefault(norm, []).append((u, row))

# Check for local favourites that are not in the google sheet
for url in unmatched_local_urls:
    row = local_favourites_index[url]
    norm = _normalize_title(row.get(local_title_column, ""))
    suggestions = unmatched_sheet_by_title.get(norm, []) if norm else []
    if suggestions:
        title = row.get(local_title_column, "")
        left_col.markdown(f"**{title}** — [link]({url})")
        for s_url, s_row in suggestions:
            s_title = s_row[google_sheet_title_column]
            s_chor = s_row[google_sheet_choreographer_column]
            left_col.markdown(f"  ↳ possible sheet match: *{s_title}* by *{s_chor}* — `{s_url}`")
            if left_col.button(f"Update sheet URL → {url}", key=f"updateL_{url}_{s_url}"):
                result = update_copperknob_url_at(s_row.name, url, url_column_index=google_sheet_copperknob_url_column)
                _cached_google_sheet.clear()
                left_col.success(result)
        continue
    lookitup = left_col.checkbox(f"No match: [{url}]({url})", key=f"lookitup_{url}")
    if lookitup:
        # Download the dance page and extract the metadata
        sheet = Stepsheet(url)
        sheet.parse()
        # Display the dance metadata
        left_col.markdown(f"### Dance Metadata for [{url}]({url})")
        left_col.json(sheet.metadata)
        write_it = left_col.button(f"Write to google sheet", key=f"writeit_{url}")
        if write_it:
            title = sheet.metadata.get("title", "Unknown Dance")
            choreographer = sheet.metadata.get("choreographer", "Unknown Choreographer")
            count = sheet.metadata.get("count", "0")
            # Convert count to integer if possible
            try:
                count = int(count)
            except ValueError:
                pass
            walls = sheet.metadata.get("wall", "0")
            # Convert walls to integer if possible
            try:
                walls = int(walls)
            except ValueError:
                pass
            level = sheet.metadata.get("level", "Unknown Level")
            song_name_and_artist = sheet.metadata.get("music", "Unknown Song - Unknown Artist")
            song_parts = song_name_and_artist.split(" - ")
            if len(song_parts) >= 2:
                song_name = song_parts[0].strip()
                song_artist = song_parts[1].strip()
            else:
                song_name = song_name_and_artist.strip()
                song_artist = "Unparsed Artist"
            result = add_dance_to_sheet(google_sheet, title, choreographer, count, walls, level, song_name, song_artist, url)
            streamlit.write(result)
            streamlit.success(f"Wrote {title} to google sheet")
            ack = streamlit.button("Acknowledge - Refresh the page to see the updated sheet")
            if ack:
                streamlit.rerun()
            streamlit.stop()


# Check for google sheet dances that are not in the local favourites
for url in unmatched_sheet_urls:
    row = google_sheet_index[url]
    name = row[google_sheet_title_column]
    norm = _normalize_title(name)
    suggestions = unmatched_local_by_title.get(norm, []) if norm else []
    if suggestions:
        rite_col.markdown(f"**{name}** — `{url}`")
        for l_url, l_row in suggestions:
            l_title = l_row.get(local_title_column, "")
            l_chor = l_row.get(local_choreographer_column, "")
            rite_col.markdown(f"  ↳ possible local match: *{l_title}* by *{l_chor}* — [{l_url}]({l_url})")
            if rite_col.button(f"Update sheet URL → {l_url}", key=f"updateR_{url}_{l_url}"):
                result = update_copperknob_url_at(row.name, l_url, url_column_index=google_sheet_copperknob_url_column)
                _cached_google_sheet.clear()
                rite_col.success(result)
        continue
    # Check if the name looks like a valid url.  If so, use it as the link
    if re.match(r'^https?://', url):
        print(f"Url looks like a url: {url}")
        search_url = url
    else:
        print(f"Url does not look like a url: {url}")
        search_url = f"https://www.copperknob.co.uk/search?Search={name.replace(' ','+')}&Beat=-1&Level=Any&Wall=-1&Lang=Any&SearchType=Any"
    rite_col.markdown(f"No match: {name}-[{url}]({search_url})")