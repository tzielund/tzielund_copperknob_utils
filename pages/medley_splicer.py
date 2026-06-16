"""Splice multiple songs into a medley by stitching them on beat boundaries.

For each input audio file, pick a start beat and an end beat. The output is the
concatenation of those slices, with an optional short crossfade at each splice
so the join doesn't click.

Prereqs:
    poetry add librosa moviepy
    brew install ffmpeg
"""

import io
import json
import os
import subprocess

import librosa
import numpy as np
import soundfile as sf
import streamlit as st

MEDLEY_OUTPUT_DIR = "medley_output/"
TARGET_SR = 44100
TRANSITION_STYLES = ["Linear", "Equal-power", "S-curve", "Hard cut", "Long fade with silence"]

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


def _apply_cuts_data(cuts_data, source_label):
    """Write a parsed cuts dict into session_state."""
    segs = cuts_data.get("segments", [])
    st.session_state["n_segments"] = int(len(segs)) if segs else 2
    st.session_state["crossfade_ms"] = int(cuts_data.get("crossfade_ms", 80))
    loaded_style = cuts_data.get("transition_style", "Linear")
    if loaded_style in TRANSITION_STYLES:
        st.session_state["transition_style"] = loaded_style
    st.session_state["preview_clicks"] = bool(cuts_data.get("preview_clicks", True))
    st.session_state["preview_click_volume"] = float(cuts_data.get("preview_click_volume", 0.5))
    for i, seg in enumerate(segs):
        st.session_state[f"medley_path_{i}"] = seg.get("path", "")
        st.session_state[f"start_unit_{i}"] = seg.get("start_unit", "Beat")
        if "start_beat" in seg:
            st.session_state[f"start_beat_{i}"] = int(seg["start_beat"])
        if "start_time" in seg:
            st.session_state[f"start_time_{i}"] = float(seg["start_time"])
        st.session_state[f"duration_{i}"] = int(seg.get("duration_beats", 32))
    st.session_state["_load_success"] = f"Loaded {source_label} ({len(segs)} segments)"


def _load_cuts_from_path(cuts_path):
    try:
        with open(cuts_path) as f:
            cuts_data = json.load(f)
    except Exception as e:
        st.session_state["_load_error"] = f"Couldn't read cut-points file: {e}"
        return
    _apply_cuts_data(cuts_data, cuts_path)


def _do_load_cuts():
    """Run the file picker, parse the chosen JSON, and apply it into session_state.

    Uses Streamlit's on_click callback timing so session_state updates are guaranteed
    to be picked up by widgets on the next rerun (which Streamlit performs automatically
    after the callback returns).
    """
    script = (
        'POSIX path of (choose file with prompt "Choose cut points JSON" '
        'of type {"public.json", "public.text", "json"})'
    )
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0 or not result.stdout.strip():
        return
    _load_cuts_from_path(result.stdout.strip())


def _do_load_selected():
    name = st.session_state.get("cuts_dropdown")
    if name and name != "—":
        _load_cuts_from_path(os.path.join(MEDLEY_OUTPUT_DIR, name))


# Find cuts files in the canonical output dir for the dropdown
os.makedirs(MEDLEY_OUTPUT_DIR, exist_ok=True)
existing_cuts = sorted(
    f for f in os.listdir(MEDLEY_OUTPUT_DIR) if f.endswith(".cuts.json")
)

dd_col, dd_btn_col, pick_col = st.columns([4, 1, 2])
dd_col.selectbox(
    "Load saved cuts",
    ["—"] + existing_cuts,
    key="cuts_dropdown",
    label_visibility="collapsed",
)
dd_btn_col.button("Load", on_click=_do_load_selected, disabled=not existing_cuts)
pick_col.button("Pick another file…", on_click=_do_load_cuts)

if msg := st.session_state.pop("_load_success", None):
    st.success(msg)
if err := st.session_state.pop("_load_error", None):
    st.error(err)

# Defaults via session_state so Load can override them. Specifying `value=` on a
# widget AND modifying its session_state from elsewhere is a conflict Streamlit
# resolves by ignoring the session_state assignment — so we avoid `value=` on
# anything we want to load into.
for _k, _default in [
    ("n_segments", 2),
    ("crossfade_ms", 80),
    ("transition_style", "Linear"),
    ("preview_clicks", True),
    ("preview_click_volume", 0.5),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _default

n_segments = st.number_input(
    "Number of segments", min_value=2, max_value=8, step=1, key="n_segments"
)
transition_style = st.selectbox("Transition style", TRANSITION_STYLES, key="transition_style")
crossfade_ms = st.slider(
    "Crossfade between segments (ms)", 0, 500, step=10, key="crossfade_ms"
)
preview_clicks = st.checkbox(
    "Add click track to previews (helps verify beat detection)", key="preview_clicks"
)
preview_click_volume = st.slider(
    "Preview click volume", 0.0, 2.0, step=0.1,
    disabled=not preview_clicks, key="preview_click_volume",
)


def crossfade_pieces(a, b, style, crossfade_samples):
    """Join two audio arrays with the chosen transition style.

    - Linear / Equal-power / S-curve: tail of `a` and head of `b` overlap with
      curves designed for different perceived loudness behaviour.
    - Hard cut: no overlap.
    - Long fade with silence: tail fades fully out, a gap of crossfade_samples
      of silence, then head fades fully in.
    """
    if style == "Hard cut" or crossfade_samples <= 0:
        return np.concatenate([a, b])
    if style == "Long fade with silence":
        if len(a) < crossfade_samples or len(b) < crossfade_samples:
            return np.concatenate([a, b])
        fade_out = np.linspace(1.0, 0.0, crossfade_samples)
        fade_in = np.linspace(0.0, 1.0, crossfade_samples)
        silence = np.zeros(crossfade_samples, dtype=a.dtype)
        return np.concatenate([
            a[:-crossfade_samples],
            a[-crossfade_samples:] * fade_out,
            silence,
            b[:crossfade_samples] * fade_in,
            b[crossfade_samples:],
        ])
    if len(a) <= crossfade_samples or len(b) <= crossfade_samples:
        return np.concatenate([a, b])
    if style == "Equal-power":
        angles = np.linspace(0.0, np.pi / 2, crossfade_samples)
        fade_out = np.cos(angles)
        fade_in = np.sin(angles)
    elif style == "S-curve":
        t = np.linspace(0.0, 1.0, crossfade_samples)
        fade_in = 3 * t * t - 2 * t * t * t
        fade_out = 1.0 - fade_in
    else:  # Linear
        fade_out = np.linspace(1.0, 0.0, crossfade_samples)
        fade_in = np.linspace(0.0, 1.0, crossfade_samples)
    overlap = a[-crossfade_samples:] * fade_out + b[:crossfade_samples] * fade_in
    return np.concatenate([a[:-crossfade_samples], overlap, b[crossfade_samples:]])


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

    # Per-segment widget defaults via session_state so Load can set them without
    # conflicting with widget `value=` parameters.
    for _k, _default in [
        (f"start_unit_{i}", "Beat"),
        (f"start_beat_{i}", 1),
        (f"start_time_{i}", 0.0),
        (f"duration_{i}", 32),
    ]:
        if _k not in st.session_state:
            st.session_state[_k] = _default

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
        "start_beat": start_beat,
        "end_beat": end_beat,
    })


if len(segments) >= 2:
    st.subheader("Transition previews")
    transition_beats = 16
    sr = segments[0]["sr"]
    crossfade_samples = int(crossfade_ms / 1000 * sr)
    for k in range(len(segments) - 1):
        a = segments[k]
        b = segments[k + 1]
        # Last transition_beats of segment a's slice (clamped to its actual start)
        tail_start_beat = max(a["start_beat"], a["end_beat"] - transition_beats)
        tail_start_idx = beat_to_sample(tail_start_beat, a["beat_times"], a["sr"], len(a["y"]))
        tail = a["y"][tail_start_idx:a["end_idx"]]
        # First transition_beats of segment b's slice (clamped to its actual end)
        head_end_beat = min(b["end_beat"], b["start_beat"] + transition_beats)
        head_end_idx = beat_to_sample(head_end_beat, b["beat_times"], b["sr"], len(b["y"]))
        head = b["y"][b["start_idx"]:head_end_idx]
        if len(tail) == 0 or len(head) == 0:
            st.caption(f"Transition {k + 1}: empty slice, nothing to preview")
            continue
        snippet = crossfade_pieces(tail, head, transition_style, crossfade_samples)
        st.caption(
            f"Transition {k + 1}: end of `{os.path.basename(a['path'])}` "
            f"→ start of `{os.path.basename(b['path'])}` "
            f"({len(tail) / sr:.2f}s + {len(head) / sr:.2f}s)"
        )
        st.audio(snippet, sample_rate=sr)

st.subheader("Stitch")
if len(segments) < 2:
    st.info("Configure at least two segments to stitch.")
    st.stop()

# Output paths derived from the first segment's filename
os.makedirs(MEDLEY_OUTPUT_DIR, exist_ok=True)
first_base = os.path.splitext(os.path.basename(segments[0]["path"]))[0]
out_path = os.path.abspath(os.path.join(MEDLEY_OUTPUT_DIR, f"{first_base}.medley.wav"))
cuts_path = os.path.abspath(os.path.join(MEDLEY_OUTPUT_DIR, f"{first_base}.cuts.json"))
st.caption(f"Output path: `{out_path}`")
st.caption(f"Cut-points path: `{cuts_path}`")

save_col, stitch_col = st.columns(2)
if save_col.button("Save cut points"):
    cuts_data = {
        "crossfade_ms": int(crossfade_ms),
        "transition_style": transition_style,
        "preview_clicks": bool(preview_clicks),
        "preview_click_volume": float(preview_click_volume),
        "segments": [],
    }
    for i, seg in enumerate(segments):
        unit = st.session_state.get(f"start_unit_{i}", "Beat")
        seg_record = {
            "path": seg["path"],
            "start_unit": unit,
            "duration_beats": int(st.session_state.get(f"duration_{i}", 32)),
        }
        if unit == "Beat":
            seg_record["start_beat"] = int(st.session_state.get(f"start_beat_{i}", 1))
        else:
            seg_record["start_time"] = float(st.session_state.get(f"start_time_{i}", 0.0))
        cuts_data["segments"].append(seg_record)
    with open(cuts_path, "w") as f:
        json.dump(cuts_data, f, indent=2)
    st.success(f"Saved {cuts_path}")

if stitch_col.button("Stitch medley"):
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
        output = crossfade_pieces(output, nxt, transition_style, crossfade_samples)

    peak = float(np.max(np.abs(output)))
    if peak > 1.0:
        output = output / peak

    sf.write(out_path, output, sr, format="WAV")
    st.session_state["medley_out_path"] = out_path
    st.success(f"Wrote {out_path} ({len(output) / sr:.1f}s)")

medley_path = st.session_state.get("medley_out_path")
if medley_path and os.path.exists(medley_path):
    st.audio(medley_path)
