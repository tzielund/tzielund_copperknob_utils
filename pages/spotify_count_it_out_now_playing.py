# Get data from Spotify and use it to count the beats in the current song.
import time

import streamlit

import spotify_streamlit_util
import spotify_util
from spotify_streamlit_util import parse_restart_list

# Spotify web token
ignore_cached_token = streamlit.checkbox("Ignore cached token", False)
spotify_web_token = spotify_streamlit_util.get_cached_spotify_token(required=False, ignore_cache=ignore_cached_token, no_confirm=True)
headers = spotify_streamlit_util.get_headers(spotify_web_token)

# local metadata about songs
song_metadata = spotify_streamlit_util.get_song_metadata()
# streamlit.json(song_metadata)

# get the currently playing song
song = spotify_util.get_current_playing_track(headers)
streamlit.json(song)
song_title = song["item"]["name"]
song_artist = song["item"]["artists"][0]["name"]
track_id = song["item"]["id"]
song_url = song["item"]["external_urls"]["spotify"]

song_progress_ms = song["progress_ms"]
song_progress_seconds = song_progress_ms / 1000
current_time = time.time()
# Adjust current time to the start of the song
song_start_time = current_time - (song_progress_seconds)
song_start_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(song_start_time))

streamlit.write(f"Currently playing: {song_title} by {song_artist}")
streamlit.write(f"Time into the song: {song_progress_seconds} seconds")
streamlit.write(f"Song started at time {song_start_datetime}")

# Now that we've got the song, get the beats
song_data = spotify_util.get_spotify_data(headers, track_id)
beats = song_data["analysis"]["beats"]

# see if we have any local metadata about this song
this_song_metadata = song_metadata.get(track_id, {})

curate_song = streamlit.checkbox("Curate this song")

if curate_song:
    # Show the data entry stuff
    this_song_metadata = spotify_streamlit_util.curate_song_metadata(this_song_metadata, beats)

intro_size_in_beats = this_song_metadata.get("intro_size_in_beats", 0)
beat_count_correction = this_song_metadata.get("beat_count_correction", 1)
counts_per_wall = this_song_metadata.get("counts_per_wall", 32)
restarts_list_string = this_song_metadata.get("restarts_list_string", "")
restart_list = parse_restart_list(restarts_list_string)
non_intro_beats_total = len(beats) - intro_size_in_beats
non_intro_count_total = non_intro_beats_total // beat_count_correction

# Build a 'script' list of counts for the song with a wall name for each (intro, wall 1, wall 2, etc.)
script = spotify_streamlit_util.build_song_script(beats, this_song_metadata)

# table of contents-- first count of each section
toc = spotify_streamlit_util.build_toc(script)

streamlit.json(toc)

# Give user option of zooming to a particular section
section_to_zoom = streamlit.selectbox("Zoom to section", toc.keys(),
                                      format_func=lambda x: f"{x} ({time.strftime('%M:%S', time.gmtime(toc[x] / 1000))})")
start_song_over = streamlit.button("Do it")
if start_song_over:
    streamlit.write("Resetting song to the start of indicated position")
    song_progress_ms = toc[section_to_zoom]
    spotify_util.seek_to(headers, song_progress_ms)
    streamlit.write("Playback set")
    # Now adjust the playback position

    song_progress_seconds = song_progress_ms / 1000
    current_time = time.time()
    # Adjust current time to the start of the song
    song_start_time = current_time - (song_progress_seconds)
    song_start_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(song_start_time))

    streamlit.write(f"Currently playing: {song_title} by {song_artist}")
    streamlit.write(f"Time into the song: {song_progress_seconds} seconds")
    streamlit.write(f"Song started at time {song_start_datetime}")


streamlit.json(script)

status_text = streamlit.status("Looking for the beat")
time_progress = streamlit.progress(0.0, "Song time")
section_8_progress = streamlit.progress(0.0, "Current 8-count section")
wall_progress = streamlit.progress(0.0, "Current wall counts")
walls_progress = streamlit.progress(0.0, "All walls")

# Now run thru the script
for struct in script:
    beat_time = struct["time_in_ms"]
    wall_number = struct.get("wall", 0)
    wait_until_time = song_start_time + beat_time / 1000
    # streamlit.write(f"Waiting until {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(wait_until_time))}")
    # now we busy wait until the beat time
    while time.time() < wait_until_time:
        pass
    label = f"{struct['name']}"
    status_text.update(label=label)

    # update the progress bars
    time_progress.progress(beat_time / song_data["duration_ms"], f"Time {time.strftime('%M:%S', time.gmtime(beat_time / 1000))}")
    # section_8_progress.progress(struct["wall_progress"], f"8-count section {struct['name']}")
    wall_progress.progress(struct["wall_progress"], f"Wall {struct['name']}")
    walls_progress.progress(struct["wall"] / wall_number, f"Wall {struct['wall']}")
    # streamlit.json(struct)



#
#
#
#
#
#
#
# # Prepare to do the counting
# beat_number = -1
# wall_number = 0
# section_8_count = 0
# status_text = streamlit.status("Starting")
# time_progress = streamlit.progress(0.0, "Time")
# total_beat_progress = streamlit.progress(0.0, "Song total")
# intro_count_progress = streamlit.progress(0.0, f"Intro beats out of {intro_size_in_beats}")
# section_8_count_progress = streamlit.progress(0.0, "Current 8-beat section")
# # section_8_total_progress = streamlit.progress(0.0, "Total 8-beat sections")
# wall_count_progress = streamlit.progress(0.0, f"Current wall counts out of {counts_per_wall}")
# total_walls = non_intro_count_total // counts_per_wall
# # adjust this for restarts
# if restart_list:
#     for wall, count in restart_list.items():
#         total_walls += 1
# wall_total_progress = streamlit.progress(0.0, f"Total walls out of {total_walls}")
#
# wall_number = 1
# wall_count = 0
# count_beats = True
# if count_beats:
#     # calculate the time.time() offset for each beat relative to the start of the song
#     for beat in beats:
#         beat_number += 1
#         wait_until_time = song_start_time + beat["start"]
#         # now we busy wait until the beat time
#         while time.time() < wait_until_time:
#             pass
#
#         # show the time progress
#         time_progress.progress(beat["start"] / song_data["duration_ms"], f"Beat {beat_number}")
#
#         # show the intro count in BEATS
#         if intro_size_in_beats > 0:
#             if beat_number <= intro_size_in_beats:
#                 intro_count_progress.progress(beat_number / intro_size_in_beats, f"Intro beat {beat_number}")
#                 status_text.update(label=f"Intro beat {beat_number}")
#                 continue
#
#         post_intro_beat_number = beat_number - intro_size_in_beats
#
#         # convert beats to counts
#         count_remainder = post_intro_beat_number % beat_count_correction
#         if count_remainder != 0:
#             continue
#         count_number = post_intro_beat_number // beat_count_correction
#         count_to_show = count_number + 1
#
#         # Calculate the count, section and wall counts
#         post_intro_count = count_number
#         section_8_count = (post_intro_count % 8)
#         section_8_total = (post_intro_count // 8)
#
#         # Calculate the wall count, but take into account restarts
#         wall_count += 1 # Counts on the current wall
#         if wall_number in restart_list:
#             wall_count_max = restart_list[wall_number]
#             is_restart_wall = True
#         else:
#             wall_count_max = counts_per_wall
#             is_restart_wall = False
#         if wall_count == wall_count_max:
#             wall_count = 0
#             wall_number += 1
#             if is_restart_wall:
#                 status_text.update(label=f"Early Restart!!! New wall {wall_number}")
#             else:
#                 status_text.update(label=f"Normal Restart. New wall {wall_number}")
#         else:
#             if is_restart_wall:
#                 status_text.update(label=f"Wall {wall_number}, Count {wall_count} (Restart at {wall_count_max})")
#             else:
#                 status_text.update(label=f"Wall {wall_number}, Count {wall_count}")
#         # Summarize in print statements
#         # print(f"count_number: {count_number}, post_intro_count: {post_intro_count}, section_8_count: {section_8_count}, section_8_total: {section_8_total}, wall_count: {wall_count}, wall_total: {wall_total}")
#
#         # Update progress bars (other than intro)
#         total_beat_progress.progress(beat_number / len(beats), f"Count {count_to_show}")
#         section_8_count_progress.progress(section_8_count / 8, f"8-beat section {section_8_count}")
#         # section_8_total_progress.progress(section_8_total / (non_intro_beats_total // 8), f"8-beat section {section_8_total}")
#         wall_count_progress.progress(wall_count / wall_count_max, f"Wall count {wall_count}")
#         wall_total_progress.progress(wall_number / total_walls, f"Wall number {wall_number}")
#
#         # # Once ever ten check the currently playing song again and restart if it has changed
#         # new_song = spotify_util.get_current_playing_track(headers)
#         # if new_song["item"]["id"] != track_id:
#         #     streamlit.write("Song has changed.  Restarting.")
#         #     streamlit.rerun()
#
#
#
