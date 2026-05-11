# Get data from Spotify and use it to count the beats in a song.
import os
import time

import streamlit
import json
from requests.structures import CaseInsensitiveDict

import spotify_streamlit_util
import spotify_util
import google_sheet_util

# Spotify web token
ignore_cached_token = streamlit.checkbox("Ignore cached token", False)
spotify_web_token = spotify_streamlit_util.get_cached_spotify_token(required=False, ignore_cache=ignore_cached_token)
headers = spotify_streamlit_util.get_headers(spotify_web_token)

# local metadata about songs
song_metadata = spotify_streamlit_util.get_song_metadata()
streamlit.json(song_metadata)

# Google sheet
dance_list = google_sheet_util.read_google_sheet()
# Get the song and artist which is in fields 5 and 6
song_list_selector = google_sheet_util.get_song_list_selector(dance_list)
streamlit.json(song_list_selector)
# Re-sort list with the songs that have local metadata first
resorted_song_list = list()
for song in song_list_selector:
    trackid = song_list_selector[song].split("/")[-1].split("?")[0]
    if trackid in song_metadata:
        resorted_song_list.insert(0, song)
        # Also add the song name to the metadata
        song_metadata[trackid]["song"] = song

    else:
        resorted_song_list.append(song)
# Now pick one of the songs
song = streamlit.selectbox("Select a song", resorted_song_list,
                           format_func=lambda x: f"✅ {x}" if song_list_selector[x] else f"❌ {x}")

# Get the song metadata, some from parsing, some from the api/cache
song_title = song.split(" by ")[0]
song_artist = song.split(" by ")[1]
song_spotify_url = song_list_selector[song]
if not song_spotify_url:
    streamlit.write(f"Spotify URL not found for {song}")
    song_title_url_encoded = song_title.replace(" ", "%20")
    spotify_search_url = "https://open.spotify.com/search/" + song_title_url_encoded
    streamlit.write(f"Search Spotify for [{song}]({spotify_search_url})")
    refresh_button = streamlit.button("Refresh")
    if refresh_button:
        if "experimental_rerun" in streamlit.__dict__:  # for Streamlit >= 1.0
            streamlit.experimental_rerun()
        streamlit.rerun()
    streamlit.stop()

streamlit.write(f"Spotify URL: {song_spotify_url}")
track_id = song_spotify_url.split("/")[-1].split("?")[0]

# Now that we've got the song, get the beats
streamlit.write("Fetching Beats")
song_data = spotify_util.get_spotify_data(headers, track_id)
beats = song_data["analysis"]["beats"]
streamlit.json(beats)

# see if we have any local metadata about this song
this_song_metadata = song_metadata.get(track_id, {})
# Use this to fill in the song metadata below

# Now we need user input to curate the Spotify data
# 1.  How many spotify beats in a song beat as people hear it (usually 1, but sometimes 2 or 4)
beat_count_correction = streamlit.number_input("How many Spotify beats in a song count", min_value=1, max_value=4,
                                               value=this_song_metadata.get("beat_count_correction", 1))

# 2.  How many counts in the intro section before the first dance wall would start
intro_size_in_beats = streamlit.number_input("Intro size in BEATS", min_value=0, max_value=len(beats),
                                                value=this_song_metadata.get("intro_size_in_beats", 0))
non_intro_beats_total = len(beats) - intro_size_in_beats
non_intro_count_total = non_intro_beats_total // beat_count_correction

# 3.  How many counts per wall (usually 32)
counts_per_wall = streamlit.number_input("Prospective count for one wall", min_value=0,
                                         value=this_song_metadata.get("counts_per_wall", 32))

# 4. Restarts-- list of walls and counts in the wall where the dance restarts before the usual count
restarts_list_string = streamlit.text_area("List of restarts (wall,count-- one per line)", value=this_song_metadata.get("restarts_list_string", ""))
restart_list = dict()
for line in restarts_list_string.split("\n"):
    if not line:
        continue
    wall, count = line.split(",")
    wall = int(wall)
    count = int(count)
    restart_list[wall] = count
    print(f"Restart at wall {wall} count {count}")
streamlit.json(restart_list)

# Summarize the size of the song in seconds, beats, and groups of beats
song_duration = song_data["duration_ms"]/1000
streamlit.write(f"Song duration: {song_duration} seconds")
streamlit.write(f"Number of counts: {len(beats)}")
streamlit.write(f"Number of 8 beat sections: {len(beats) // 8}")
streamlit.write(f"Number of {counts_per_wall} beat sections: {len(beats) // counts_per_wall}")

# Take one of these actions
# 1.  Count the beats
# 2.  play the song
# 3.  Show the beats during the song (ie, both)
# 4.  Save the curated data for this song

play_song = streamlit.checkbox("Play the song")
count_beats = streamlit.checkbox("Count the beats")
save_data = streamlit.checkbox("Save the curated data")
do_it = streamlit.button("Do it")
if not do_it:
    streamlit.stop()

if save_data:
    song_metadata[track_id] = {"beat_count_correction": beat_count_correction,
                               "intro_size_in_beats": intro_size_in_beats,
                               "counts_per_wall": counts_per_wall,
                               "restarts_list_string": restarts_list_string}
    spotify_streamlit_util.save_song_metadata(song_metadata)

if play_song:
    spotify_util.play_track(headers, track_id)
    spotify_util.seek_to(headers, 0)

beat_number = -1
wall_number = 0
section_8_count = 0
status_text = streamlit.status("Starting")
total_beat_progress = streamlit.progress(0.0, "Song total")
intro_count_progress = streamlit.progress(0.0, f"Intro beats out of {intro_size_in_beats}")
section_8_count_progress = streamlit.progress(0.0, "Current 8-beat section")
# section_8_total_progress = streamlit.progress(0.0, "Total 8-beat sections")
wall_count_progress = streamlit.progress(0.0, f"Current wall counts out of {counts_per_wall}")
total_walls = non_intro_count_total // counts_per_wall
# adjust this for restarts
if restart_list:
    for wall, count in restart_list.items():
        total_walls += 1
wall_total_progress = streamlit.progress(0.0, f"Total walls out of {total_walls}")

wall_number = 1
wall_count = 0
if count_beats:
    # calculate the time.time() offset for each beat relative to the start of the song
    current_time = time.time() # in seconds as a float
    for beat in beats:
        beat_number += 1
        wait_until_time = current_time + beat["start"]
        # now we busy wait until the beat time
        while time.time() < wait_until_time:
            pass


        # show the intro count in BEATS
        if intro_size_in_beats > 0:
            if beat_number <= intro_size_in_beats:
                intro_count_progress.progress(beat_number / intro_size_in_beats, f"Intro beat {beat_number}")
                status_text.update(label=f"Intro beat {beat_number}")
                continue

        post_intro_beat_number = beat_number - intro_size_in_beats

        # convert beats to counts
        count_remainder = post_intro_beat_number % beat_count_correction
        if count_remainder != 0:
            continue
        count_number = post_intro_beat_number // beat_count_correction
        count_to_show = count_number + 1

        # Calculate the count, section and wall counts
        post_intro_count = count_number
        section_8_count = (post_intro_count % 8)
        section_8_total = (post_intro_count // 8)

        # Calculate the wall count, but take into account restarts
        wall_count += 1 # Counts on the current wall
        if wall_number in restart_list:
            wall_count_max = restart_list[wall_number]
            is_restart_wall = True
        else:
            wall_count_max = counts_per_wall
            is_restart_wall = False
        if wall_count == wall_count_max:
            wall_count = 0
            wall_number += 1
            if is_restart_wall:
                status_text.update(label=f"Early Restart!!! New wall {wall_number}")
            else:
                status_text.update(label=f"Normal Restart. New wall {wall_number}")
        else:
            if is_restart_wall:
                status_text.update(label=f"Wall {wall_number}, Count {wall_count} (Restart at {wall_count_max})")
            else:
                status_text.update(label=f"Wall {wall_number}, Count {wall_count}")
        # Summarize in print statements
        # print(f"count_number: {count_number}, post_intro_count: {post_intro_count}, section_8_count: {section_8_count}, section_8_total: {section_8_total}, wall_count: {wall_count}, wall_total: {wall_total}")

        # Update progress bars (other than intro)
        total_beat_progress.progress(beat_number / len(beats), f"Count {count_to_show}")
        section_8_count_progress.progress(section_8_count / 8, f"8-beat section {section_8_count}")
        # section_8_total_progress.progress(section_8_total / (non_intro_beats_total // 8), f"8-beat section {section_8_total}")
        wall_count_progress.progress(wall_count / wall_count_max, f"Wall count {wall_count}")
        wall_total_progress.progress(wall_number / total_walls, f"Wall number {wall_number}")


streamlit.stop()

if true:
    # Note the current time in milliseconds
    start_time = time.time()
    # Set up several count progress bars
    intro_beat_progress = streamlit.progress(0.0, "Intro remaining")
    total_beat_progress = streamlit.progress(0.0, "Non-Intro remaining")
    beat_8_progress = streamlit.progress(0.0, "8-beat section")
    beat_16_progress = streamlit.progress(0.0, "16-beat section")
    beat_24_progress = streamlit.progress(0.0, "24-beat section")
    beat_32_progress = streamlit.progress(0.0, "32-beat section")
    # Now repeatedly wait until the next beat and then write the count out
    count_number = -1 * intro_size_in_counts
    for beat in beats:
        beat_start_time_in_milliseconds = beat["start"] * 1000
        # Wait until the beat time
        beat_time = beat_start_time_in_milliseconds - start_time
        print(f"Waiting until {beat_time} milliseconds")
        # Do a busy wait until the beat time
        while time.time() * 1000 < beat_start_time_in_milliseconds:
            print(f"Waiting for {beat_time} milliseconds")
            pass
        # # Let's try using the time.sleep function
        # time.sleep(beat_wait_time / 1000)
        # Update the progress bars
        if count_number < 0:
            intro_beat_progress.progress((count_number + intro_size_in_counts) / intro_size_in_counts)
        else:
            total_beat_progress.progress(count_number / len(beats))
            beat_8_progress.progress(count_number % 8 / 8)
            beat_16_progress.progress(count_number % 16 / 16)
            beat_24_progress.progress(count_number % 24 / 24)
            beat_32_progress.progress(count_number % 32 / 32)
        streamlit.write(f"Beat {count_number}")

        count_number += 1

