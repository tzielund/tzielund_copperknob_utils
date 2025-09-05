import streamlit
import json
import pandas

track_name = "Come On Eileen"
track_artist = "Dexys Midnight Runners"
trackid = "3MrWxJaD2AT0W9DjWF64Vm"
cache_dir = "spotify_cache/"
track_attribute_dir = f"{cache_dir}track_attributes"
track_attribute_file = f"{track_attribute_dir}/{trackid}.json"
# Read the data from the cache
track_attributes = None
with open(track_attribute_file) as IN:
    track_attributes = json.load(IN)

beats = track_attributes["analysis"]["beats"]
# list the beats as a table
beats_df = pandas.DataFrame(beats)
streamlit.dataframe(beats_df)