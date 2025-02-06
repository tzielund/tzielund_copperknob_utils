# Compare the sheet to the favourites to see if there are any new dances to add to the favourites.

# Read data from exported favourites file
import streamlit

from google_sheet_util import read_google_sheet
from local_fav_utils import read_local_favourites, local_favourites_file_in_project

local_favourites = read_local_favourites(local_favourites_file_in_project)
google_sheet = read_google_sheet()

local_copperknob_url_column = "URL"
google_sheet_copperknob_url_column = 7

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

# Check for local favourites that are not in the google sheet
for url in local_favourites_index.keys():
    if url not in google_sheet_index:
        left_col.markdown(f"No match: [{url}]({url})")

# Check for google sheet dances that are not in the local favourites
for url in google_sheet_index.keys():
    if url not in local_favourites_index:
        name = google_sheet_index[url][0]
        rite_col.markdown(f"No match: {name}-[{url}]({url})")