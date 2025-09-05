import json
import streamlit

import spotify_streamlit_util
from spotify_streamlit_util import parse_restart_list, build_song_script

# Spotify web token
ignore_cached_token = streamlit.checkbox("Ignore cached token", False)
spotify_web_token = spotify_streamlit_util.get_cached_spotify_token(required=False, ignore_cache=ignore_cached_token, no_confirm=True)
headers = spotify_streamlit_util.get_headers(spotify_web_token)


def get_test_data(filename):
    with open(filename) as IN:
        return json.load(IN)

def test_restart_parse(test_data):
    metadata = test_data["metadata"]
    parsed_restart_list = parse_restart_list(metadata.get("restarts_list_string"))
    asserted_restart_list = test_data["restarts_parsed"]
    # change the keys to integers
    parsed_restart_list = {int(k): v for k, v in parsed_restart_list.items()}
    assert parsed_restart_list == asserted_restart_list

# Test Til You Can't
streamlit.header("Til You Can't test")
tyc_input_file = "tilyoucant_beats.json"
test_data = get_test_data(tyc_input_file)
beats = test_data["analysis"]["beats"]
metadata = test_data["metadata"]
parsed_restart_list = parse_restart_list(metadata.get("restarts_list_string"))
asserted_restart_list = test_data["metadata"]["restarts_list"]
assert parse_restart_list(metadata.get("restarts_list_string")) == {4: 27}

streamlit.write("All the beats")
streamlit.write(beats)

# Make a list of integers from 0 to len(beats)
beat_numbers = list(range(len(beats)))
zoom_to_button = streamlit.selectbox("Zoom to section", beat_numbers,
                                     format_func=lambda x: f"{x}: {beats[x]['start']}")

script = build_song_script(beats, metadata)
streamlit.write(script)

def test_built_ttf(self):
    # Load test data
    test_data = dict()
    with open(ttf_input_file) as IN:
        beats = json.load(IN)
    metadata = {
        "beat_count_correction": 1,
        "first_count_beat": 0,
        "intro_size_in_beats": 0,
        "counts_per_wall": 32,
        "restarts_list_string": ""
    }


