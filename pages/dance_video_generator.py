"""Render an MP4 video that plays an MP3 with timed text labels overlaid.

This is the first slice: manually-edited CSV of labels gets baked into a black-background
video synced to the audio. Later additions: pull labels from a Copperknob stepsheet and
auto-generate wall/restart banners from beat-curation data (like spotify_count_it_out.py).

Prereqs:
    poetry add moviepy
    brew install ffmpeg
"""

import io
import os
import subprocess

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

VIDEO_OUTPUT_DIR = "video_output/"
DEFAULT_MP3_PATH = "/Users/tom.zielund/Music/Music/04 - Watermelon Crawl.mp3"
DEFAULT_LABELS = (
    "time,text,kind,duration\n"
    "0.0,Intro,wall,4.0\n"
    "8.0,Wall 1,wall,2.0\n"
    "8.5,Step right,step,2.0\n"
    "10.5,Step left,step,2.0\n"
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


def generate_video(audio_path, labels_df, out_path, max_seconds=None):
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
        t = float(row["time"])
        if t >= duration:
            continue
        text = str(row["text"]).strip()
        kind = str(row.get("kind", "step")).strip() or "step"
        dur = float(row.get("duration", 2.0))
        dur = min(dur, duration - t)
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

st.subheader("Labels")
st.markdown(
    "Columns: `time` (seconds), `text`, `kind` (step / wall / restart), `duration` (seconds, default 2)."
)
labels_csv = st.text_area("Labels CSV", value=DEFAULT_LABELS, height=240)

try:
    labels_df = pd.read_csv(io.StringIO(labels_csv))
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
            max_seconds=preview_seconds if preview_only else None,
        )
    st.session_state["video_out_path"] = out_path

video_path = st.session_state.get("video_out_path")
if video_path and os.path.exists(video_path):
    st.success(f"Wrote {video_path}")
    with open(video_path, "rb") as f:
        st.video(f.read())
