# Spotify cacher-- cache playlists from Spotify
import os
import time

import pandas
import streamlit
from requests.structures import CaseInsensitiveDict

import spotify_util
from google_sheet_util import read_google_sheet

# Check for the Spotify Web Token in the session state
if "spotify_web_token" in streamlit.session_state:
    spotify_web_token = streamlit.session_state["spotify_web_token"]
    refresh_token_button = streamlit.button("Refresh token")
    if refresh_token_button:
        spotify_web_token = ""
        # Overwrite the cache file
        if os.path.exists("spotify_web_token.txt"):
            os.remove("spotify_web_token.txt")
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
# Write to the cache file and session state
with open("spotify_web_token.txt", "w") as f:
    f.write(spotify_web_token)
streamlit.session_state["spotify_web_token"] = spotify_web_token

headers = CaseInsensitiveDict()
headers["Authorization"] = spotify_web_token
headers["Content-Type"] = "application/json"


# Get the user's playlists
playlists = spotify_util.get_cached_playlist_list(headers)
# Locate the "Zizis line dance" playlist
playlist = None
for item in playlists:
    if item["name"] == "Zizis line dance":
        playlist = item
if not playlist:
    streamlit.write(f"Could not find Zizis line dance playlist")
    streamlit.stop()


# Get the songs
ignore_cache = streamlit.button("Ignore cache")

playlist_id = playlist['id']
playlist_data = spotify_util.cache_playlist(headers, playlist_id, playlist, ignore_cache=ignore_cache)
# List the songs by name and artist with a link to the song
# streamlit.json(playlist_data)
streamlit.header("Zizis line dance")
show_all = streamlit.checkbox("Show all songs")
if show_all:
    for trackid in playlist_data.keys():
        streamlit.markdown(f"* {playlist_data[trackid]['name']} by {playlist_data[trackid]['artists'][0]['name']}")

# Fetch data from the google sheet
google_sheet = read_google_sheet()
# streamlit.write(google_sheet)
song_name_index = dict()
for index,row in google_sheet.iterrows():
    song_name = row[5]
    song_name_norm = song_name.lower().replace(" ", "")
    song_name_index[song_name_norm] = row

left_col, rite_col = streamlit.columns(2)
left_col.header("Spotify unmatched")
rite_col.header("Google Sheet unmatched")

# Check for songs in the google sheet that are not in the playlist
for song_name_norm in song_name_index:
    song_row = song_name_index[song_name_norm]
    song_name = song_row[5]
    song_name_norm = song_name.lower().replace(" ", "")
    found = False
    for trackid in playlist_data.keys():
        track_title = playlist_data[trackid]['name']
        track_title_norm = track_title.lower().replace(" ", "")
        if track_title_norm == song_name_norm:
            found = True
    if not found:
        search_url = "https://open.spotify.com/search/" + song_name.replace(" ", "+")
        left_col.markdown(f"No match: [{song_name}]({search_url})")

# Check for songs in the playlist that are not in the google sheet
for trackid in playlist_data.keys():
    track_title = playlist_data[trackid]['name']
    track_title_norm = track_title.lower().replace(" ", "")
    found = False
    if track_title_norm in song_name_index:
        found = True
    if not found:
        rite_col.markdown(f"No match: {track_title}")


# Lookup additional song attributes on Spotify API
attribute_data = dict()
all_data = dict()
for selected_song in playlist_data.keys():
    selected_attributes = dict()
    selected_attributes["name"] = playlist_data[selected_song]['name']
    selected_attributes["artist"] = playlist_data[selected_song]['artists'][0]['name']
    song_row = playlist_data[selected_song]
    track_id = playlist_data[selected_song]['id']
    # track_id = "11dFghVXANMlKmJXsNCbNl"
    attributes = spotify_util.get_spotify_data(headers, track_id)
    # danceability, energy, key, loudness, mode, speechiness, acousticness, instrumentalness, liveness, valence, tempo, duration_ms, time_signature\
    selected_attributes["danceability"] = attributes["danceability"]
    selected_attributes["energy"] = attributes["energy"]
    selected_attributes["key"] = attributes["key"]
    selected_attributes["loudness"] = attributes["loudness"]
    selected_attributes["mode"] = attributes["mode"]
    selected_attributes["speechiness"] = attributes["speechiness"]
    selected_attributes["acousticness"] = attributes["acousticness"]
    selected_attributes["instrumentalness"] = attributes["instrumentalness"]
    selected_attributes["liveness"] = attributes["liveness"]
    selected_attributes["valence"] = attributes["valence"]
    selected_attributes["tempo"] = attributes["tempo"]
    selected_attributes["duration_ms"] = attributes["duration_ms"]
    selected_attributes["time_signature"] = attributes["time_signature"]

    # streamlit.write(attributes)
    attribute_data[track_id] = selected_attributes
    all_data[track_id] = attributes
# Display selected_attributes as a table
table = pandas.DataFrame(attribute_data).T
streamlit.dataframe(table)

# seek_test = streamlit.button("Seek test")
# if seek_test:
#     # Seek to 10 seconds
#     spotify_util.seek_to(headers, 10000)

# Select a song to display the attributes
song_to_display = streamlit.selectbox("Select a song to display attributes", playlist_data.keys(),
                                      format_func=lambda x: playlist_data[x]['name'])
if song_to_display:
    all_attributes =all_data[song_to_display]
    track_id = song_to_display
    sections = all_attributes["analysis"]["sections"]
    bars = all_attributes["analysis"]["bars"]

    # for each section, list the bars
    section_number = 0
    for section in sections:
        section_number += 1
        streamlit.write(f"Section {section_number}")
        # Note the time signature
        time_signature = section["time_signature"]
        if time_signature == 4:
            streamlit.markdown("* Time signature is 4/4, common time")
        else:
            streamlit.markdown(f"* Time signature is {time_signature}")
        section_duration = section["duration"]
        # Count the number of bars in the section
        bar_count = 0
        for bar in bars:
            if bar['start'] >= section['start'] and bar['start'] < section['start'] + section['duration']:
                bar_count += 1
        beat_count = section["duration"] * time_signature
        streamlit.markdown(f"* Section duration: {section_duration} seconds, {bar_count} bars or {beat_count} beats")
        play_this_section = streamlit.button(f"Play section {section_number}")
        start_offset_in_milliseconds = section["start"] * 1000
        duration_in_milliseconds = section["duration"] * 1000
        if play_this_section:
            spotify_util.play_section(headers, track_id, start_offset_in_milliseconds ,duration_in_milliseconds)

    streamlit.write(all_attributes)