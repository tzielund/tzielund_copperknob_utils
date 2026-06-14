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
import soundfile as sf
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

VIDEO_OUTPUT_DIR = "video_output/"
CLICK_OUTPUT_DIR = "click_track_output/"
EXTRACTED_AUDIO_DIR = "extracted_audio/"
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm")
DEFAULT_MP3_PATH = "/Users/tom.zielund/Music/Music/04 - Watermelon Crawl.mp3"
DEFAULT_LABELS = (
    "beat,text,kind,duration_beats\n"
    "# Lines starting with # are ignored\n"
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
    # Five label kinds. Layout convention: center is reserved for `title`; the corners
    # carry persistent wall/restart markers; step + count stack near the bottom.
    if kind == "wall":
        font = _load_font(70)
        color = (255, 200, 50, 255)
        h_align = "left"
        anchor_y = 50
    elif kind == "restart":
        font = _load_font(70)
        color = (255, 100, 100, 255)
        h_align = "right"
        anchor_y = 50
    elif kind == "title":
        font = _load_font(110)
        color = (255, 255, 255, 255)
        h_align = "center"
        anchor_y = None  # vertically centered after measuring
    elif kind == "count":
        font = _load_font(70)
        color = (100, 200, 255, 255)
        h_align = "center"
        anchor_y = VIDEO_SIZE[1] - 110
    else:  # step
        font = _load_font(80)
        color = (255, 255, 255, 255)
        h_align = "center"
        anchor_y = VIDEO_SIZE[1] - 210

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    edge_padding = 50
    if h_align == "left":
        x = edge_padding
    elif h_align == "right":
        x = VIDEO_SIZE[0] - edge_padding - tw
    else:
        x = (VIDEO_SIZE[0] - tw) // 2
    if anchor_y is None:
        anchor_y = (VIDEO_SIZE[1] - th) // 2
    draw.text((x, anchor_y), text, font=font, fill=color)
    return np.array(img)


def is_video_file(path):
    return path.lower().endswith(VIDEO_EXTS)


@st.cache_data(show_spinner="Extracting audio from video…")
def extract_audio_from_video(video_path):
    """Pull the audio track out of a video into a WAV file. Returns the WAV path."""
    from moviepy import VideoFileClip

    os.makedirs(EXTRACTED_AUDIO_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(video_path))[0]
    out_path = os.path.abspath(os.path.join(EXTRACTED_AUDIO_DIR, f"{base}.wav"))
    clip = VideoFileClip(video_path)
    try:
        clip.audio.write_audiofile(out_path, logger=None)
    finally:
        clip.close()
    return out_path


def audio_path_for(source_path):
    """Return a path to an audio file usable by librosa. Extracts from video if needed."""
    if is_video_file(source_path):
        return extract_audio_from_video(source_path)
    return source_path


@st.cache_data(show_spinner="Detecting beats…")
def analyze_audio(audio_path):
    """Load audio + detect beats. Cached per audio_path. Returns (y, sr, tempo, beat_times)."""
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
    return y, sr, tempo_val, beat_times


def detect_beats(audio_path):
    """Backwards-compatible wrapper returning just (tempo, beat_times)."""
    _, _, tempo, beat_times = analyze_audio(audio_path)
    return tempo, beat_times


@st.cache_data(show_spinner="Muxing click track into video…")
def make_video_with_clicks(source_path, click_volume):
    """Build an MP4 with the original video stream and a click-mixed audio stream.

    Uses ffmpeg stream-copy on the video so this is fast; only audio is re-encoded.
    """
    audio_path_local = audio_path_for(source_path)
    clicks_audio_path = make_click_track(audio_path_local, click_volume)

    os.makedirs(CLICK_OUTPUT_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(source_path))[0]
    out_path = os.path.abspath(os.path.join(CLICK_OUTPUT_DIR, f"{base}.with_clicks.mp4"))

    cmd = [
        "ffmpeg", "-y",
        "-i", source_path,
        "-i", clicks_audio_path,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")
    return out_path


@st.cache_data(show_spinner="Mixing click track…")
def make_click_track(audio_path, click_volume):
    """Generate a click-track-mixed WAV in CLICK_OUTPUT_DIR, return the path."""
    y, sr, _, beat_times = analyze_audio(audio_path)
    clicks = librosa.clicks(times=np.asarray(beat_times), sr=sr, length=len(y))
    mixed = y + click_volume * clicks
    peak = float(np.max(np.abs(mixed)))
    if peak > 1.0:
        mixed = mixed / peak
    os.makedirs(CLICK_OUTPUT_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(audio_path))[0]
    out_path = os.path.abspath(os.path.join(CLICK_OUTPUT_DIR, f"{base}.clicks.wav"))
    sf.write(out_path, mixed, sr, format="WAV")
    return out_path


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


def generate_video(source_path, labels_df, out_path, beat_times, max_seconds=None, label_offset_beats=0.0):
    # moviepy 2.x: import from `moviepy`, not `moviepy.editor`; methods are with_*, subclipped
    from moviepy import (
        AudioFileClip,
        ColorClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
    )

    output_fps = FPS
    if is_video_file(source_path):
        src = VideoFileClip(source_path).resized(VIDEO_SIZE)
        duration = src.duration
        if max_seconds:
            duration = min(duration, max_seconds)
            src = src.subclipped(0, duration)
        audio = src.audio
        background = src.with_audio(None)  # avoid audio being applied twice when we re-attach
        if src.fps:
            output_fps = src.fps  # match source fps to avoid re-encoding sync drift
    else:
        audio = AudioFileClip(source_path)
        duration = audio.duration
        if max_seconds:
            duration = min(duration, max_seconds)
            audio = audio.subclipped(0, duration)
        background = ColorClip(VIDEO_SIZE, color=(0, 0, 0), duration=duration)

    overlays = [background]

    for _, row in labels_df.iterrows():
        beat = float(row["beat"]) + label_offset_beats
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
        fps=output_fps,
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
        'POSIX path of (choose file with prompt "Choose audio or video file" '
        'of type {"public.audio", "public.movie", "public.mpeg-4", "mp3", "wav", "mp4"})'
    )
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=300
    )
    if result.returncode == 0 and result.stdout.strip():
        st.session_state["video_audio_path"] = result.stdout.strip()
        st.rerun()

source_path = path_col.text_input("Audio or video file path", key="video_audio_path")

if not (source_path and os.path.exists(source_path)):
    st.info("Choose an audio or video file to begin.")
    st.stop()

is_video = is_video_file(source_path)
st.caption(f"Source: `{source_path}`  ·  type: {'video' if is_video else 'audio'}")

# For video sources, extract audio once for librosa + previews
audio_path = audio_path_for(source_path)
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

st.subheader("Preview")
if is_video:
    preview_options = [
        "Audio - original",
        "Audio - with clicks",
        "Video - original",
        "Video - with clicks",
        "None",
    ]
else:
    preview_options = ["Audio - original", "Audio - with clicks", "None"]
preview_mode = st.radio("Preview", preview_options, horizontal=True, index=0)

needs_clicks = preview_mode in ("Audio - with clicks", "Video - with clicks")
if needs_clicks:
    click_volume = st.slider("Click volume (relative to music)", 0.0, 2.0, 0.5, step=0.1)

if preview_mode == "Audio - original":
    st.audio(audio_path)
elif preview_mode == "Audio - with clicks":
    st.audio(make_click_track(audio_path, click_volume))
elif preview_mode == "Video - original":
    st.video(source_path)
elif preview_mode == "Video - with clicks":
    try:
        st.video(make_video_with_clicks(source_path, click_volume))
    except RuntimeError as e:
        st.error(str(e))

st.subheader("Labels")
st.markdown(
    "Columns: `beat` (1-indexed, fractional OK; `+N` = N beats past previous row's last "
    "beat), `text`, `kind` (step / wall / restart / count / title), `duration_beats` "
    "(how many beats the label stays on screen). Lines starting with `#` are treated as "
    "comments and skipped."
)
labels_csv = st.text_area("Labels CSV", value=DEFAULT_LABELS, height=240)

try:
    # Strip lines whose first non-whitespace character is '#'. Done by line so that '#'
    # inside text cells (e.g. "Step #5") isn't treated as a comment marker.
    filtered_csv = "\n".join(
        line for line in labels_csv.splitlines() if not line.lstrip().startswith("#")
    )
    labels_df = pd.read_csv(io.StringIO(filtered_csv), dtype={"beat": str})
    labels_df = resolve_beats(labels_df)
except Exception as e:
    st.error(f"Couldn't parse labels CSV: {e}")
    st.stop()
st.dataframe(labels_df, hide_index=True)

st.subheader("Render")
preview_only = st.checkbox("Preview first N seconds only", value=True)
preview_seconds = st.number_input("Preview seconds", min_value=5, max_value=600, value=30, step=5)
label_offset_beats = st.number_input(
    "Label offset (beats)",
    value=0.0,
    step=0.05,
    format="%.2f",
    help=(
        "Added to every label's beat. Positive values shift labels later (use this if "
        "labels appear earlier than they should). Try 0.25 if labels feel a quarter beat early."
    ),
)

os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
base = os.path.splitext(os.path.basename(source_path))[0]
suffix = ".preview.mp4" if preview_only else ".mp4"
out_path = os.path.abspath(os.path.join(VIDEO_OUTPUT_DIR, f"{base}{suffix}"))
st.caption(f"Output path: `{out_path}`")

if st.button("Generate video"):
    with st.spinner("Rendering — this can take a minute…"):
        generate_video(
            source_path,
            labels_df,
            out_path,
            beat_times,
            max_seconds=preview_seconds if preview_only else None,
            label_offset_beats=label_offset_beats,
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
