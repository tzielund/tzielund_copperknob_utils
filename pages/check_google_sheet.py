# Read a google sheet with compiled favourites

import streamlit
from google_sheet_util import spreadsheet_url, read_google_sheet

streamlit.write("Google Sheet Favourites")
streamlit.markdown(f"[{spreadsheet_url}]({spreadsheet_url})")

df = read_google_sheet()
streamlit.dataframe(df)

# Note any dances that don't have a Copperknob URL
for index, row in df.iterrows():
    if row[7] == "" or row[7] is None or row[7] == "TBD" or row[7] == "???":
        dance_name_plaintext = row[0]
        dance_name = row[0].replace(" ", "+")
        copperknob_search_url = f"https://www.copperknob.co.uk/search?Search={dance_name}&Beat=-1&Level=Any&Wall=-1&Lang=Any&SearchType=Title"
        streamlit.markdown(f"No Copperknob URL for [{dance_name_plaintext}]({copperknob_search_url})")


#List the dances with links to Copperknob, BringTheFun, and Spotify
for index, row in df.iterrows():
    name = row[0]
    copperknob_url = row[7]
    bringthefun_url = "https://bringthefun.dance/search?q=" + name.replace(" ", "+")
    spotify_song = row[5].replace(" ", "+")
    spotify_artist = row[6].replace(" ", "+")
    spotify_search_url = "https://open.spotify.com/search/" + spotify_song + "+" + spotify_artist
    streamlit.markdown(f"{name}: [CopperKnob]({copperknob_url}), [BringTheFun]({bringthefun_url}), [Spotify]({spotify_search_url})")
