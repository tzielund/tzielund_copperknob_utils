# Uses spotify api to get the currently playing song and check for best dance match
import os
import time

import requests
import streamlit
from bs4 import BeautifulSoup
from requests.structures import CaseInsensitiveDict
import spotify_util

streamlit.title("Now Playing in Spotify")

# Check for the Spotify Web Token in the session state
if "spotify_web_token" in streamlit.session_state:
    spotify_web_token = streamlit.session_state["spotify_web_token"]
else:
    spotify_web_token = ""

# Check for spotify web token in local cache file
if os.path.exists("spotify_web_token.txt"):
    # Check the file age.  If more than 1 hour don't use it
    file_age = os.path.getmtime("spotify_web_token.txt")
    current_time = time.time()
    if current_time - file_age < 3600:
        with open("spotify_web_token.txt", "r") as f:
            spotify_web_token = f.read()

if not spotify_web_token:
    # Data entry field for spotify web token
    spotify_web_token = streamlit.text_input("Spotify Web Token", "")

if not spotify_web_token:
    streamlit.stop()

headers = CaseInsensitiveDict()
headers["Authorization"] = spotify_web_token
headers["Content-Type"] = "application/json"

# Get the google sheet data
from google_sheet_util import spreadsheet_url, read_google_sheet

df = read_google_sheet()

current_track = spotify_util.get_current_playing_track(headers)
if current_track:
    track = current_track["item"]
    track_name = track["name"]
    artist = track["artists"][0]["name"]
    album = track["album"]["name"]
    album_cover = track["album"]["images"][0]["url"]
    streamlit.write(f"Currently playing {track_name} by {artist} from {album}")
    streamlit.image(album_cover, width=200)

    # See if the song is in the Google Sheet
    found = False
    track_name_normalized = track_name.lower().replace(" ", "")
    artist_normalized = artist.lower().replace(" ", "")
    for index, row in df.iterrows():
        sheet_song_name = row[5]
        sheet_song_normalized = sheet_song_name.lower().replace(" ", "")
        sheet_artist = row[6]
        sheet_artist_normalized = sheet_artist.lower().replace(" ", "")
        if sheet_song_normalized == track_name_normalized:
            if sheet_artist == "" or sheet_artist_normalized == artist_normalized:
                found = True
                streamlit.write(f"Found {track_name} by {artist} in the Google Sheet")
                # show more info about the dance
                streamlit.write(f"Dance name: {row[0]}")
                streamlit.write(f"Choreographer: {row[1]}")
                streamlit.write(f"Counts: {row[2]}")
                streamlit.write(f"Walls: {row[3]}")
                streamlit.write(f"Level: {row[4]}")
                streamlit.write(f"Stepsheet link: {row[7]}")
                break


    if not found:
        streamlit.write(f"Did not find {track_name} by {artist} in the Google Sheet")
        # streamlit.dataframe(df)

        # Offer to skip this track
        skip = streamlit.button("Skip this track")
        if skip:
            spotify_util.next_track(headers)
            time.sleep(3)
            streamlit.rerun()
        previous = streamlit.button("Previous track")
        if previous:
            spotify_util.previous_track(headers)
            time.sleep(3)
            streamlit.rerun()

        # Look up track by name on Copperknob using search URL
        track_name = streamlit.text_input("Track Name", value=track_name)

        url_safe_name = track_name.replace(" ", "+")
        copperknob_search_url = f"https://www.copperknob.co.uk/search?Order=Rating&Lang=Any&SearchType=Music&Level=Any&Beat=-1&Wall=-1&Search={url_safe_name}&recnum=0"
        streamlit.write(f"Search Copperknob for {track_name} by {artist} [here]({copperknob_search_url})")
        result = requests.get(copperknob_search_url)
        #parse the HTML to get the dance list
        soup = BeautifulSoup(result.text, 'html.parser')
        # Find all list items
        # find all divs with class listitem
        list_items = soup.find_all("div", {"class": "listitem"})
        # Filter list items that start with "Michael Jackson Cha Cha"
        dances = list_items


        streamlit.write(f"Found {len(dances)} dances")
        for dance in dances:
            # Parse the dance metadata
            # Title is the content of a span with class listTitleColor1
            title = dance.find("span", {"class": "listTitleColor1"}).text
            # Choreographer is the content of a span with class listTitleColor2
            choreographer = dance.find("span", {"class": "listTitleColor2"}).text

            # Metadata including counts, leve, and music details are in a p tag with class listIcons
            metadata = dance.find("p", {"class": "listIcons"})
            metadata_contents = metadata.text

            has_demo = dance.find("span", {"class": "videoicon"})
            has_teach = dance.find("span", {"class": "teachicon"})
            has_music = dance.find("span", {"class": "musicicon"})
            has_comments = dance.find("span", {"class": "commentsicon"})

            # Ignore any when there's no icons other than music
            if not has_demo and not has_teach and not has_comments:
                continue
            if has_demo:
                metadata_contents += "|D"
            if has_teach:
                metadata_contents += "|T"
            if has_music:
                metadata_contents += "|M"
            if has_comments:
                metadata_contents += "|C"

            # url is the href of the first a tag in the div
            url = dance.find("a")["href"]
            link = f"[{title}]({url}) by {choreographer}: {metadata_contents}"

            # Write this all out
            streamlit.markdown(f"* {link}")

            # streamlit.write(dance)



        # streamlit.write(result.text)
