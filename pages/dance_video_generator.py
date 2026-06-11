"""Render an MP4 video that plays an MP3 with timed text labels overlaid.

This is the first slice: manually-edited CSV of labels gets baked into a black-background
video synced to the audio. Later additions: pull labels from a Copperknob stepsheet and
auto-generate wall/restart banners from beat-curation data (like spotify_count_it_out.py).

Prereqs:
    poetry add moviepy
    brew install ffmpeg
"""

import datetime
import io
import os
import shutil
import subprocess
import tempfile

import librosa
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

VIDEO_OUTPUT_DIR = "video_output/"
DEFAULT_MP3_PATH = "/Users/tom.zielund/Music/Music/04 - Watermelon Crawl.mp3"
DEFAULT_LABELS = (
    "beat,text,kind,duration_beats\n"
    "1,Intro,wall,32\n"
    "+1,Wall 1,wall,32\n"
    "33,Step 1,step,4\n"
    "+1,Step 2,step,4\n"
)

VIDEO_SIZE = (1280, 720)
FPS = 24
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]

st.set_page_config(page_title="Dance Video Generator", layout="wide")
st.title("Dance Video Generator")


def _load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _render_label_frame(text, kind):
    """Return an RGBA numpy array sized to VIDEO_SIZE with the text composited in."""
    img = Image.new("RGBA", VIDEO_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if kind == "wall":
        font = _load_font(110)
        color = (255, 200, 50, 255)
        anchor_y = 130
    elif kind == "restart":
        font = _load_font(120)
        color = (255, 100, 100, 255)
        anchor_y = VIDEO_SIZE[1] // 2 - 60
    else:  # step
        font = _load_font(80)
        color = (255, 255, 255, 255)
        anchor_y = VIDEO_SIZE[1] // 2 - 40
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (VIDEO_SIZE[0] - tw) // 2
    draw.text((x, anchor_y), text, font=font, fill=color)
    return np.array(img)


@st.cache_data(show_spinner="Detecting beats…")
def detect_beats(audio_path):
    """Return (tempo, beat_times list). Cached per audio_path."""
    # Load via temp copy so librosa doesn't have to deal with weird names
    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(audio_path)[1] or ".mp3", delete=False) as tmp:
        with open(audio_path, "rb") as src:
            tmp.write(src.read())
        tmp_path = tmp.name
    try:
        y, sr = librosa.load(tmp_path, sr=None, mono=True)
    finally:
        os.unlink(tmp_path)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    tempo_val = float(tempo) if np.isscalar(tempo) else float(np.asarray(tempo).flatten()[0])
    return tempo_val, beat_times


def resolve_beats(labels_df):
    """Resolve relative beat references (+N / -N) to absolute beats.

    +N means N beats past the previous row's last beat (inclusive end), i.e.
    `prev_start + prev_duration - 1 + N`. So a row with duration 16 ending at
    beat 16 followed by "+1" resolves to beat 17.

    Plain numbers (e.g. "33", "33.5") are treated as absolute.

    Rows with missing or unparseable `beat` are skipped. Missing `duration_beats`
    defaults to 4. NaN propagation through +/- references is prevented by skipping
    bad rows entirely — earlier valid rows still anchor subsequent +/- references.
    """
    out = labels_df.copy()
    out["beat"] = out["beat"].astype(str).str.strip()
    if "duration_beats" in out.columns:
        out["duration_beats"] = pd.to_numeric(out["duration_beats"], errors="coerce").fillna(4.0)
    else:
        out["duration_beats"] = 4.0

    abs_beats = []
    keep_indices = []
    prev_last_beat = 0.0
    for i, row in out.iterrows():
        cell = row["beat"]
        if not cell or cell.lower() in ("nan", "none"):
            continue
        try:
            if cell.startswith("+") or cell.startswith("-"):
                abs_beat = prev_last_beat + float(cell)
            else:
                abs_beat = float(cell)
        except ValueError:
            continue
        dur = float(row["duration_beats"])
        prev_last_beat = abs_beat + dur - 1
        abs_beats.append(abs_beat)
        keep_indices.append(i)

    out = out.loc[keep_indices].copy()
    out["beat"] = abs_beats
    return out


def beat_to_time(beat, beat_times):
    """Convert a 1-indexed (possibly fractional) beat number to seconds.

    Linearly interpolates between adjacent detected beats. Extrapolates outside the
    detected range using the nearest beat interval, so beats before the first detected
    beat or after the last still get a sensible time.
    """
    if not beat_times:
        return 0.0
    idx = float(beat) - 1.0
    if idx <= 0:
        if len(beat_times) >= 2:
            interval = beat_times[1] - beat_times[0]
            return beat_times[0] + idx * interval
        return beat_times[0]
    i_lo = int(idx)
    frac = idx - i_lo
    if i_lo >= len(beat_times) - 1:
        if len(beat_times) >= 2:
            interval = beat_times[-1] - beat_times[-2]
            return beat_times[-1] + (idx - (len(beat_times) - 1)) * interval
        return beat_times[-1]
    return beat_times[i_lo] + frac * (beat_times[i_lo + 1] - beat_times[i_lo])


def generate_video(audio_path, labels_df, out_path, beat_times, max_seconds=None):
    # moviepy 2.x: import from `moviepy`, not `moviepy.editor`; methods are with_*, subclipped
    from moviepy import AudioFileClip, ColorClip, CompositeVideoClip, ImageClip

    audio = AudioFileClip(audio_path)
    duration = audio.duration
    if max_seconds:
        duration = min(duration, max_seconds)
        audio = audio.subclipped(0, duration)

    background = ColorClip(VIDEO_SIZE, color=(0, 0, 0), duration=duration)
    overlays = [background]

    for _, row in labels_df.iterrows():
        beat = float(row["beat"])
        t = beat_to_time(beat, beat_times)
        if t >= duration or t < 0:
            continue
        text = str(row["text"]).strip()
        kind = str(row.get("kind", "step")).strip() or "step"
        dur_beats = float(row.get("duration_beats", 4.0))
        dur = beat_to_time(beat + dur_beats, beat_times) - t
        dur = min(max(dur, 0.1), duration - t)
        frame = _render_label_frame(text, kind)
        clip = (
            ImageClip(frame, transparent=True)
            .with_duration(dur)
            .with_start(t)
            .with_position((0, 0))
        )
        overlays.append(clip)

    video = CompositeVideoClip(overlays, size=VIDEO_SIZE).with_audio(audio)
    video.write_videofile(
        out_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",  # render fast; quality is fine for previews
        threads=4,
        logger=None,
    )


# ─── UI ───────────────────────────────────────────────────────────────

if "video_audio_path" not in st.session_state:
    st.session_state["video_audio_path"] = DEFAULT_MP3_PATH

path_col, pick_col = st.columns([5, 1])
if pick_col.button("Pick file…"):
    script = (
        'POSIX path of (choose file with prompt "Choose audio file" '
        'of type {"mp3", "wav", "m4a", "flac"})'
    )
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=300
    )
    if result.returncode == 0 and result.stdout.strip():
        st.session_state["video_audio_path"] = result.stdout.strip()
        st.rerun()

audio_path = path_col.text_input("Audio file path", key="video_audio_path")

if not (audio_path and os.path.exists(audio_path)):
    st.info("Choose an audio file to begin.")
    st.stop()

st.caption(f"Source: `{audio_path}`")

tempo, beat_times = detect_beats(audio_path)
c1, c2, c3 = st.columns(3)
c1.metric("Tempo (BPM)", f"{tempo:.1f}")
c2.metric("Beats detected", len(beat_times))
c3.metric("Last beat (s)", f"{beat_times[-1]:.1f}" if beat_times else "—")

with st.expander("Beat-to-time reference (first 32)"):
    st.dataframe(
        pd.DataFrame({
            "beat": list(range(1, min(33, len(beat_times) + 1))),
            "time_s": [round(beat_times[i], 3) for i in range(min(32, len(beat_times)))],
        }),
        hide_index=True,
    )

st.subheader("Labels")
st.markdown(
    "Columns: `beat` (1-indexed, fractional OK; `+N` = N beats past previous row's last "
    "beat), `text`, `kind` (step / wall / restart), `duration_beats` (how many beats the "
    "label stays on screen)."
)
labels_csv = st.text_area("Labels CSV", value=DEFAULT_LABELS, height=240)

try:
    labels_df = pd.read_csv(io.StringIO(labels_csv), dtype={"beat": str})
    labels_df = resolve_beats(labels_df)
except Exception as e:
    st.error(f"Couldn't parse labels CSV: {e}")
    st.stop()
st.dataframe(labels_df, hide_index=True)

st.subheader("Render")
preview_only = st.checkbox("Preview first N seconds only", value=True)
preview_seconds = st.number_input("Preview seconds", min_value=5, max_value=600, value=30, step=5)

os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
base = os.path.splitext(os.path.basename(audio_path))[0]
suffix = ".preview.mp4" if preview_only else ".mp4"
out_path = os.path.abspath(os.path.join(VIDEO_OUTPUT_DIR, f"{base}{suffix}"))
st.caption(f"Output path: `{out_path}`")

if st.button("Generate video"):
    with st.spinner("Rendering — this can take a minute…"):
        generate_video(
            audio_path,
            labels_df,
            out_path,
            beat_times,
            max_seconds=preview_seconds if preview_only else None,
        )
    st.session_state["video_out_path"] = out_path

video_path = st.session_state.get("video_out_path")
if video_path and os.path.exists(video_path):
    st.success(f"Wrote {video_path}")
    msg_col, save_col = st.columns([3, 1])
    if save_col.button("Save a copy"):
        stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        root, ext = os.path.splitext(video_path)
        saved_path = f"{root}.{stamp}{ext}"
        shutil.copy2(video_path, saved_path)
        msg_col.success(f"Saved to `{saved_path}`")
    with open(video_path, "rb") as f:
        st.video(f.read())
