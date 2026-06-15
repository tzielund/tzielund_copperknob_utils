"""Splice multiple songs into a medley by stitching them on beat boundaries.

For each input audio file, pick a start beat and an end beat. The output is the
concatenation of those slices, with an optional short crossfade at each splice
so the join doesn't click.

Prereqs:
    poetry add librosa moviepy
    brew install ffmpeg
"""

import io
import os
import subprocess

import librosa
import numpy as np
import soundfile as sf
import streamlit as st

MEDLEY_OUTPUT_DIR = "medley_output/"
TARGET_SR = 44100

st.set_page_config(page_title="Medley Splicer", layout="wide")
st.title("Medley Splicer")


@st.cache_data(show_spinner="Detecting beats…")
def analyze_for_medley(audio_path):
    """Load + beat-detect at a fixed SR so all segments can be concatenated."""
    y, sr = librosa.load(audio_path, sr=TARGET_SR, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    tempo_val = float(tempo) if np.isscalar(tempo) else float(np.asarray(tempo).flatten()[0])
    return y, sr, tempo_val, beat_times


def pick_audio_file():
    """Open the macOS file picker and return the selected path (or None)."""
    script = (
        'POSIX path of (choose file with prompt "Choose audio file" '
        'of type {"public.audio", "mp3", "wav", "m4a", "flac"})'
    )
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=300
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def beat_to_sample(beat, beat_times, sr, total_samples):
    """Convert a 1-indexed beat number to a sample index, clamped to [0, total_samples]."""
    if beat < 1:
        return 0
    idx = beat - 1
    if idx >= len(beat_times):
        return total_samples
    return min(int(beat_times[idx] * sr), total_samples)


n_segments = st.number_input("Number of segments", min_value=2, max_value=8, value=2, step=1)
crossfade_ms = st.slider("Crossfade between segments (ms)", 0, 500, 80, step=10)
preview_clicks = st.checkbox("Add click track to previews (helps verify beat detection)", value=True)
preview_click_volume = st.slider(
    "Preview click volume", 0.0, 2.0, 0.5, step=0.1, disabled=not preview_clicks
)


def mix_clicks(slice_y, beat_times, slice_start_t, sr, click_volume):
    """Return slice_y with clicks overlaid at any beat times falling inside the slice."""
    slice_duration = len(slice_y) / sr
    rel_times = [
        bt - slice_start_t
        for bt in beat_times
        if 0.0 <= bt - slice_start_t < slice_duration
    ]
    if not rel_times:
        return slice_y
    clicks = librosa.clicks(times=np.asarray(rel_times), sr=sr, length=len(slice_y))
    mixed = slice_y + click_volume * clicks
    peak = float(np.max(np.abs(mixed)))
    if peak > 1.0:
        mixed = mixed / peak
    return mixed

segments = []
for i in range(int(n_segments)):
    st.subheader(f"Segment {i + 1}")
    path_key = f"medley_path_{i}"
    if path_key not in st.session_state:
        st.session_state[path_key] = ""

    path_col, pick_col = st.columns([5, 1])
    if pick_col.button("Pick…", key=f"pick_{i}"):
        picked = pick_audio_file()
        if picked:
            st.session_state[path_key] = picked
            st.rerun()
    path = path_col.text_input("Audio path", key=path_key)

    if not path:
        st.info("Pick a file to enable this segment.")
        continue
    if not os.path.exists(path):
        st.error(f"File not found: {path}")
        continue

    y, sr, tempo, beat_times = analyze_for_medley(path)
    duration = len(y) / sr
    n_beats = len(beat_times)
    st.caption(
        f"Duration: {duration:.1f}s  ·  BPM ≈ {tempo:.1f}  ·  Beats detected: {n_beats}"
    )

    start_unit = st.radio(
        "Start by", ["Beat", "Time (s)"], horizontal=True, key=f"start_unit_{i}"
    )
    sb_col, dur_col = st.columns(2)
    if start_unit == "Beat":
        start_beat = int(
            sb_col.number_input(
                "Start beat",
                min_value=1,
                max_value=n_beats,
                value=1,
                step=1,
                key=f"start_beat_{i}",
            )
        )
        seg_start_t = beat_times[start_beat - 1] if start_beat - 1 < n_beats else 0.0
    else:
        typed_time = float(
            sb_col.number_input(
                "Start (seconds)",
                min_value=0.0,
                max_value=float(duration),
                value=0.0,
                step=0.5,
                format="%.2f",
                key=f"start_time_{i}",
            )
        )
        # Snap to the preceding beat (largest beat_time <= typed_time)
        preceding_idx = -1
        for k, t in enumerate(beat_times):
            if t <= typed_time:
                preceding_idx = k
            else:
                break
        if preceding_idx >= 0:
            start_beat = preceding_idx + 1
            seg_start_t = beat_times[preceding_idx]
        else:
            start_beat = 1
            seg_start_t = 0.0

    # No max_value: changing start_beat would shrink the bound and clamp the user's typed
    # value. Slice math handles overflow by clamping to the song's last sample.
    duration_beats = int(
        dur_col.number_input(
            "Duration (beats)",
            min_value=1,
            value=32,
            step=1,
            key=f"duration_{i}",
        )
    )
    end_beat = start_beat + duration_beats  # exclusive; beat_to_sample clamps to total
    beats_available = max(0, n_beats - start_beat + 1)
    if duration_beats > beats_available:
        st.caption(
            f"⚠ Requested {duration_beats} beats but only ~{beats_available} remain "
            "from this start — slice will end at the song's last sample."
        )

    seg_end_t = beat_times[end_beat - 1] if end_beat - 1 < n_beats else duration
    if start_unit == "Beat":
        st.caption(
            f"Slice: beat {start_beat} ({seg_start_t:.2f}s) for {duration_beats} beats "
            f"→ {seg_end_t:.2f}s, {seg_end_t - seg_start_t:.2f}s of audio"
        )
    else:
        st.caption(
            f"Slice: {typed_time:.2f}s snapped to beat {start_beat} ({seg_start_t:.2f}s) "
            f"for {duration_beats} beats → {seg_end_t:.2f}s, "
            f"{seg_end_t - seg_start_t:.2f}s of audio"
        )

    # Both modes snap the start to a beat boundary (Time mode rounds down to the preceding beat).
    slice_start_idx = max(0, min(int(seg_start_t * sr), len(y)))
    slice_end_idx = beat_to_sample(end_beat, beat_times, sr, len(y))
    if slice_end_idx > slice_start_idx:
        slice_y = y[slice_start_idx:slice_end_idx]
        if preview_clicks:
            slice_y = mix_clicks(slice_y, beat_times, slice_start_idx / sr, sr, preview_click_volume)
        st.audio(slice_y, sample_rate=sr)
    else:
        st.warning("Empty slice — adjust start/end beats.")

    segments.append({
        "path": path,
        "y": y,
        "sr": sr,
        "beat_times": beat_times,
        "start_idx": slice_start_idx,
        "end_idx": slice_end_idx,
    })


st.subheader("Stitch")
if len(segments) < 2:
    st.info("Configure at least two segments to stitch.")
    st.stop()

# Output path is derived from the first segment's filename
os.makedirs(MEDLEY_OUTPUT_DIR, exist_ok=True)
first_base = os.path.splitext(os.path.basename(segments[0]["path"]))[0]
out_path = os.path.abspath(os.path.join(MEDLEY_OUTPUT_DIR, f"{first_base}.medley.wav"))
st.caption(f"Output path: `{out_path}`")

if st.button("Stitch medley"):
    sr = segments[0]["sr"]  # all loaded at TARGET_SR, so this matches
    crossfade_samples = int(crossfade_ms / 1000 * sr)

    pieces = []
    for s in segments:
        if s["end_idx"] > s["start_idx"]:
            pieces.append(s["y"][s["start_idx"]:s["end_idx"]])

    if not pieces:
        st.error("All segments resolved to empty slices.")
        st.stop()

    output = pieces[0]
    for nxt in pieces[1:]:
        if crossfade_samples > 0 and len(output) > crossfade_samples and len(nxt) > crossfade_samples:
            fade_out = np.linspace(1.0, 0.0, crossfade_samples)
            fade_in = np.linspace(0.0, 1.0, crossfade_samples)
            overlap = output[-crossfade_samples:] * fade_out + nxt[:crossfade_samples] * fade_in
            output = np.concatenate([output[:-crossfade_samples], overlap, nxt[crossfade_samples:]])
        else:
            output = np.concatenate([output, nxt])

    peak = float(np.max(np.abs(output)))
    if peak > 1.0:
        output = output / peak

    sf.write(out_path, output, sr, format="WAV")
    st.session_state["medley_out_path"] = out_path
    st.success(f"Wrote {out_path} ({len(output) / sr:.1f}s)")

medley_path = st.session_state.get("medley_out_path")
if medley_path and os.path.exists(medley_path):
    st.audio(medley_path)
