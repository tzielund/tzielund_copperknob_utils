# Provides a common Streamlit UI for getting a Spotify Web Token
import json

import requests
import streamlit
import os
import time

from requests.structures import CaseInsensitiveDict

def get_cached_spotify_token(ignore_cache=False, required=True, no_confirm=False):
    # make sure we have Spotify credentials
    spotify_web_token = ""

    # 1. Check for spotify web token in local cache file
    if os.path.exists("spotify_web_token.txt"):
        # Check the file age.  If more than 1 hour don't use it
        file_age = os.path.getmtime("spotify_web_token.txt")
        current_time = time.time()
        if current_time - file_age < 3600:
            with open("spotify_web_token.txt", "r") as f:
                spotify_web_token = f.read()
                if not ignore_cache:
                    greet_user(spotify_web_token)
                    return spotify_web_token

    # 2. Data entry field for spotify web token
    spotify_web_token = streamlit.text_input("Spotify Web Token", spotify_web_token)
    if not spotify_web_token:
        if required:
            streamlit.write("You will need your spotify web token to lookup data or play songs.")
            streamlit.stop()
        else:
            streamlit.write("No Spotify Web Token provided.  You may proceed without it but some features may not work.")
            return None

    # Write to the cache file and session state
    with open("spotify_web_token.txt", "w") as f:
        f.write(spotify_web_token)

    # test it out by getting the current user's profile using plain requests
    if not no_confirm:
        greet_user(spotify_web_token)
    return spotify_web_token

def greet_user(spotify_web_token):
    headers = get_headers(spotify_web_token)
    profile_response = requests.get('https://api.spotify.com/v1/me', headers=headers)
    if profile_response.status_code != 200:
        streamlit.write("Web token does not appear to be valid.")
    else:
        profile_display_name = profile_response.json()["display_name"]
        streamlit.write("Welcome back, " + profile_display_name)

def get_headers(spotify_web_token):
    headers = CaseInsensitiveDict()
    headers["Authorization"] = spotify_web_token
    headers["Content-Type"] = "application/json"
    return headers

LOCAL_SONG_METADATA_FILE = "song_metadata.json"

def get_song_metadata():
    if os.path.exists(LOCAL_SONG_METADATA_FILE):
        with open(LOCAL_SONG_METADATA_FILE) as IN:
            song_metadata = json.load(IN)
    else:
        song_metadata = dict()
    return song_metadata


def save_song_metadata(song_metadata):
    with open(LOCAL_SONG_METADATA_FILE, 'w') as OUT:
        OUT.write(json.dumps(song_metadata, indent=4))

def parse_restart_list (restarts_list_string):
    restart_list = dict()
    for line in restarts_list_string.split("\n"):
        if not line:
            continue
        wall, count = line.split(",")
        wall = int(wall)
        count = int(count)
        restart_list[wall] = count
    return restart_list

def curate_song_metadata(this_song_metadata, beats):
    # Now we need user input to curate the Spotify data
    # How many spotify beats in a song beat as people hear it (usually 1, but sometimes 2 or 4)
    beat_count_correction = streamlit.number_input("How many Spotify beats in a song count", min_value=1, max_value=4,
                                                   value=this_song_metadata.get("beat_count_correction", 1))

    # Which beat is the first count of the song (usually 0, but sometimes there's a delay)
    first_count_beat = streamlit.number_input("Which beat is the first count of the song", min_value=0, max_value=len(beats),
                                              value=this_song_metadata.get("first_count_beat", 0))

    # How many counts in the intro section before the first dance wall would start
    intro_size_in_beats = streamlit.number_input("Intro size in BEATS", min_value=0, max_value=len(beats),
                                                 value=this_song_metadata.get("intro_size_in_beats", 0))

    # How many counts per wall (usually 32)
    counts_per_wall = streamlit.number_input("Prospective count for one wall", min_value=0,
                                             value=this_song_metadata.get("counts_per_wall", 32))

    # 4. Restarts-- list of walls and counts in the wall where the dance restarts before the usual count
    restarts_list_string = streamlit.text_area("List of restarts (wall,count-- one per line)", value=this_song_metadata.get("restarts_list_string", ""))

    # Offer to save the data
    save_data = streamlit.button("Save the curated data")
    if save_data:
        this_song_metadata = {"beat_count_correction": beat_count_correction,
                              "first_count_beat": first_count_beat,
                              "intro_size_in_beats": intro_size_in_beats,
                              "counts_per_wall": counts_per_wall,
                              "restarts_list_string": restarts_list_string}
        save_song_metadata(this_song_metadata)
        streamlit.write("Data saved to local file.")

    return this_song_metadata

def build_song_script(beats, this_song_metadata):
    # Build the song script-- list of counts with a label, wall number, and count number
    intro_size_in_beats = this_song_metadata.get("intro_size_in_beats", 0)
    beat_count_correction = this_song_metadata.get("beat_count_correction", 1)
    first_count_beat = this_song_metadata.get("first_count_beat", 0)
    restart_list = parse_restart_list(this_song_metadata.get("restarts_list_string", ""))
    counts_per_wall = this_song_metadata.get("counts_per_wall", 32)

    # Make correction for spotify beats to song counts
    script = list()
    beat_number = first_count_beat * -1
    count_number = 0
    for beat in beats:
        beat_number += 1
        if beat_number < 0:
            continue
        remainder = beat_number % beat_count_correction
        if remainder != 0:
            continue
        count_number += 1
        count = dict()
        count["start"] = beat["start"]
        count["count"] = count_number
        script.append(count)

    # Now we have a list of counts.
    # Split out the intro
    intro_counts = script[:intro_size_in_beats]
    count_number = 0
    for count in intro_counts:
        count_number += 1
        count["wall"] = 0
        count["wall_count"] = count_number
        count["section"] = "Intro"
        count["name"] = f"Intro {count['count']}"

    all_wall_counts = script[intro_size_in_beats:]
    wall_number = 0
    count_number = 0
    wall_count = 0
    for count in script:
        count_number += 1
        count["wall"] = 0
        count["wall_progress"] = 0.0
        count["section"] = "Intro"
        count["name"] = f"Intro {count['count']}"

    # for each wall (including intro), add the counts


    # Beat correction-- skip to the first count beat and then take every nth beat
    corrected_beats = beats[first_count_beat:]
    beat_index = first_count_beat - 1
    for beat in beats[first_count_beat:]:
        beat_number += 1
        count_remainder = beat_number % beat_count_correction
        if count_remainder != 0:
            continue
        corrected_beats.append(beat)
    beats = corrected_beats
    # Insert all the intro beats
    beat_number = 0
    for beat in beats[:intro_size_in_beats]:
        beat_number += 1
        struct = dict()
        struct["section"] = "Intro"
        struct["name"] = f"Intro {beat_number}"
        struct["time_in_ms"] = int(beat["start"] * 1000)
        struct["count_overall"]
        struct["wall"] = 0
        struct["wall_progress"] = beat_number / intro_size_in_beats
        script.append(struct)
    # Subarray of beats that are not in the intro; accounting for beat correction
    non_intro_beats = list()
    beat_number = -1
    for beat in beats[intro_size_in_beats:]:
        beat_number += 1
        count_remainder = beat_number % beat_count_correction
        if count_remainder != 0:
            continue
        count_number = beat_number // beat_count_correction
        count_to_show = count_number + 1
        beat["count"] = count_to_show
        non_intro_beats.append(beat)
    # Now we have the non-intro beats, we can build the outline
    wall_number = 1
    wall_count = 0
    for beat in non_intro_beats:
        wall_count += 1
        counts_per_wall = restart_list.get(wall_number, counts_per_wall)
        if wall_count > counts_per_wall:
            wall_count = 1
            wall_number += 1
        struct = dict()
        struct["section"] = f"Wall {wall_number}"
        struct["name"] = f"Wall {wall_number}: {wall_count}/{counts_per_wall}"
        struct["time_in_ms"] = int(beat["start"] * 1000)
        struct["wall"] = wall_number
        struct["wall_progress"] = wall_count / counts_per_wall
        script.append(struct)

    return script

def build_toc(script):
    toc = dict()
    for struct in script:
        if struct["section"] not in toc:
            toc[struct["section"]] = struct["time_in_ms"]
    return toc