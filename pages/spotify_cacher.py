# Spotify cacher-- cache playlists from Spotify
import os
import time

import pandas
import streamlit
from requests.structures import CaseInsensitiveDict

import spotify_streamlit_util
import spotify_util
from google_sheet_util import read_google_sheet

# Spotify web token
ignore_cached_token = streamlit.checkbox("Ignore cached token", False)
spotify_web_token = spotify_streamlit_util.get_cached_spotify_token(required=False, ignore_cache=ignore_cached_token)
headers = spotify_streamlit_util.get_headers(spotify_web_token)
if not spotify_web_token:
    streamlit.stop()

# Get the user's playlists
playlists = spotify_util.get_cached_playlist_list(headers)
# Locate the "Zizis line dance" playlist
playlist = None
practice_playlist = None
for item in playlists:
    if item["name"] == "Zizis line dance":
        playlist = item
        streamlit.write("Found Zizis line dance playlist")
    if item["name"] == "Practice Playlist":
        practice_playlist = item
        streamlit.write("Found practice playlist")
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
# song name is column 5, artist is column 6, spotify url is column 8
google_sheet = read_google_sheet()
# streamlit.write(google_sheet)
song_name_index = dict()
practice_dance_index = dict()
for index,row in google_sheet.iterrows():
    song_name = row[5]
    song_name_norm = song_name.lower().replace(" ", "")
    song_name_index[song_name_norm] = row
    song_status = row[11]
    if song_status in ["Studying", "Needs work", "Favorite"]:
        practice_dance_index[song_name_norm] = row

left_col, rite_col = streamlit.columns(2)
left_col.header("Spotify unmatched")
rite_col.header("Google Sheet unmatched")

# Check for songs in the google sheet that are not in the playlist
auto_add_list = dict()
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
        # Check if there's a spotify url
        spotify_url = song_row[8]
        if spotify_url:
            # left_col.markdown(f"No match but song known: [{song_name}]({spotify_url})")
            auto_add_list[song_name] = spotify_url
        else:
            left_col.markdown(f"No match: [{song_name}]({search_url})")

if auto_add_list:
    auto_add_button = streamlit.button("Add these songs to the playlist")
    for song_name, spotify_url in auto_add_list.items():
        streamlit.markdown(f"[{song_name}]({spotify_url})")
    if auto_add_button:
        track_ids = []
        for song_name, spotify_url in auto_add_list.items():
            # identify the track id from the spotify url
            track_id = spotify_url.split("/")[-1]
            track_ids.append(track_id)
        spotify_util.add_to_playlist(headers, playlist_id, track_ids)
        streamlit.write("Songs added to the playlist")

# Check for songs in the playlist that are not in the google sheet
for trackid in playlist_data.keys():
    track_title = playlist_data[trackid]['name']
    track_title_norm = track_title.lower().replace(" ", "")
    found = False
    if track_title_norm in song_name_index:
        found = True
    if not found:
        rite_col.markdown(f"No match: {track_title}")


# streamlit.stop() # Audio analysis no longer supported
#
# # Lookup additional song attributes on Spotify API
# attribute_data = dict()
# all_data = dict()
# for selected_song in playlist_data.keys():
#     selected_attributes = dict()
#     selected_attributes["name"] = playlist_data[selected_song]['name']
#     selected_attributes["artist"] = playlist_data[selected_song]['artists'][0]['name']
#     song_row = playlist_data[selected_song]
#     track_id = playlist_data[selected_song]['id']
#     # track_id = "11dFghVXANMlKmJXsNCbNl"
#     attributes = spotify_util.get_spotify_data(headers, track_id)
#     # danceability, energy, key, loudness, mode, speechiness, acousticness, instrumentalness, liveness, valence, tempo, duration_ms, time_signature\
#     selected_attributes["danceability"] = attributes["danceability"]
#     selected_attributes["energy"] = attributes["energy"]
#     selected_attributes["key"] = attributes["key"]
#     selected_attributes["loudness"] = attributes["loudness"]
#     selected_attributes["mode"] = attributes["mode"]
#     selected_attributes["speechiness"] = attributes["speechiness"]
#     selected_attributes["acousticness"] = attributes["acousticness"]
#     selected_attributes["instrumentalness"] = attributes["instrumentalness"]
#     selected_attributes["liveness"] = attributes["liveness"]
#     selected_attributes["valence"] = attributes["valence"]
#     selected_attributes["tempo"] = attributes["tempo"]
#     selected_attributes["duration_ms"] = attributes["duration_ms"]
#     selected_attributes["time_signature"] = attributes["time_signature"]
#
#     # streamlit.write(attributes)
#     attribute_data[track_id] = selected_attributes
#     all_data[track_id] = attributes
# # Display selected_attributes as a table
# table = pandas.DataFrame(attribute_data).T
# streamlit.dataframe(table)

# seek_test = streamlit.button("Seek test")
# if seek_test:
#     # Seek to 10 seconds
#     spotify_util.seek_to(headers, 10000)

# Select a song to display the attributes
# song_to_display = streamlit.selectbox("Select a song to display attributes", playlist_data.keys(),
#                                       format_func=lambda x: playlist_data[x]['name'])
# if song_to_display:
#     all_attributes =all_data[song_to_display]
#     track_id = song_to_display
#     sections = all_attributes["analysis"]["sections"]
#     bars = all_attributes["analysis"]["bars"]
#
#     # for each section, list the bars
#     section_number = 0
#     for section in sections:
#         section_number += 1
#         streamlit.write(f"Section {section_number}")
#         # Note the time signature
#         time_signature = section["time_signature"]
#         if time_signature == 4:
#             streamlit.markdown("* Time signature is 4/4, common time")
#         else:
#             streamlit.markdown(f"* Time signature is {time_signature}")
#         section_duration = section["duration"]
#         # Count the number of bars in the section
#         bar_count = 0
#         for bar in bars:
#             if bar['start'] >= section['start'] and bar['start'] < section['start'] + section['duration']:
#                 bar_count += 1
#         beat_count = section["duration"] * time_signature
#         streamlit.markdown(f"* Section duration: {section_duration} seconds, {bar_count} bars or {beat_count} beats")
#         play_this_section = streamlit.button(f"Play section {section_number}")
#         start_offset_in_milliseconds = section["start"] * 1000
#         duration_in_milliseconds = section["duration"] * 1000
#         if play_this_section:
#             spotify_util.play_section(headers, track_id, start_offset_in_milliseconds ,duration_in_milliseconds)
#
#     streamlit.write(all_attributes)


# Also update practice playlist
streamlit.write("Updating practice playlist")
if practice_playlist:
    practice_playlist_id = practice_playlist['id']
    practice_playlist_data = spotify_util.cache_playlist(headers, practice_playlist_id, practice_playlist, ignore_cache=ignore_cache)
    # List the songs by name and artist with a link to the song
    streamlit.json(practice_playlist_data)
    # Check for songs in the google sheet that are not in the playlist
    auto_add_list = dict()
    for song_name_norm in practice_dance_index:
        song_row = song_name_index[song_name_norm]
        song_name = song_row[5]
        song_name_norm = song_name.lower().replace(" ", "")
        found = False
        for trackid in practice_playlist_data.keys():
            track_title = practice_playlist_data[trackid]['name']
            track_title_norm = track_title.lower().replace(" ", "")
            if track_title_norm == song_name_norm:
                found = True
        if not found:
            search_url = "https://open.spotify.com/search/" + song_name.replace(" ", "+")
            # streamlit.markdown(f"Add: [{song_name}]({search_url})")
            # Check if there's a spotify url
            spotify_url = song_row[8]
            if spotify_url:
                # left_col.markdown(f"No match but song known: [{song_name}]({spotify_url})")
                auto_add_list[song_name] = spotify_url
            else:
                left_col.markdown(f"No match: [{song_name}]({search_url})")
    if auto_add_list:
        auto_add_button = streamlit.button("Add these songs to the practice playlist")
        for song_name, spotify_url in auto_add_list.items():
            streamlit.markdown(f"[{song_name}]({spotify_url})")
        if auto_add_button:
            track_ids = []
            for song_name, spotify_url in auto_add_list.items():
                # identify the track id from the spotify url
                track_id = spotify_url.split("/")[-1]
                track_ids.append(track_id)
            spotify_util.add_to_playlist(headers, practice_playlist_id, track_ids)
            streamlit.write("Songs added to the playlist")