"""Detect beats in an audio file with librosa and visualize them on the waveform.

Prereqs:
    poetry add librosa
    brew install ffmpeg   # needed for MP3/M4A/etc. decoding
"""

import os
import tempfile

import altair as alt
import librosa
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="MP3 Beat Detector", layout="wide")
st.title("MP3 Beat Detector")

source = st.radio("Audio source", ["Upload file", "Local path"], horizontal=True)
audio_bytes = None
filename = None

if source == "Upload file":
    uploaded = st.file_uploader("Audio file", type=["mp3", "wav", "m4a", "flac", "ogg"])
    if uploaded:
        audio_bytes = uploaded.getvalue()
        filename = uploaded.name
else:
    local_path = st.text_input("Path to audio file", value="")
    if local_path:
        try:
            with open(local_path, "rb") as f:
                audio_bytes = f.read()
            filename = os.path.basename(local_path)
        except OSError as e:
            st.error(f"Couldn't read file: {e}")

if not audio_bytes:
    st.info("Upload or point to an audio file to begin.")
    st.stop()


@st.cache_data(show_spinner="Loading + analyzing audio...")
def analyze(audio_bytes, suffix):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        y, sr = librosa.load(tmp_path, sr=None, mono=True)
    finally:
        os.unlink(tmp_path)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    tempo_val = float(tempo) if np.isscalar(tempo) else float(np.asarray(tempo).flatten()[0])
    return y, sr, tempo_val, beat_times


suffix = os.path.splitext(filename)[1] if filename else ".mp3"
y, sr, tempo, beat_times = analyze(audio_bytes, suffix)
duration = len(y) / sr

c1, c2, c3 = st.columns(3)
c1.metric("Tempo (BPM)", f"{tempo:.1f}")
c2.metric("Duration", f"{duration:.1f} s")
c3.metric("Beats detected", len(beat_times))

st.audio(audio_bytes)

st.subheader("Waveform + beat markers")
left, right = st.columns(2)
t_start = left.number_input("Window start (s)", 0.0, float(duration), 0.0, step=1.0)
t_end = right.number_input("Window end (s)", float(t_start), float(duration), min(20.0, float(duration)), step=1.0)

samples = slice(int(t_start * sr), int(t_end * sr))
window_y = y[samples]

# Downsample to ~4000 points so Altair stays responsive even on long windows
max_points = 4000
if len(window_y) > max_points:
    step = len(window_y) // max_points
    window_y = window_y[::step]
times = np.linspace(t_start, t_end, len(window_y))

waveform_df = pd.DataFrame({"time": times, "amplitude": window_y})
beats_in_window = [bt for bt in beat_times if t_start <= bt <= t_end]
beats_df = pd.DataFrame({"time": beats_in_window})

wave = alt.Chart(waveform_df).mark_line(strokeWidth=0.5, color="steelblue").encode(
    x=alt.X("time:Q", title="Time (s)", scale=alt.Scale(domain=(t_start, t_end))),
    y=alt.Y("amplitude:Q", title="Amplitude"),
)
beat_rules = alt.Chart(beats_df).mark_rule(color="red", strokeWidth=1, opacity=0.6).encode(
    x="time:Q",
)
st.altair_chart((wave + beat_rules).properties(height=300), use_container_width=True)

st.subheader("Beat list")
df = pd.DataFrame({
    "beat_index": range(1, len(beat_times) + 1),
    "time_seconds": [round(t, 3) for t in beat_times],
    "interval_seconds": [round(beat_times[i] - beat_times[i - 1], 3) if i > 0 else None for i in range(len(beat_times))],
})
st.dataframe(df, hide_index=True)
st.download_button(
    "Download beats CSV",
    df.to_csv(index=False),
    file_name=(filename or "audio") + ".beats.csv",
    mime="text/csv",
)
