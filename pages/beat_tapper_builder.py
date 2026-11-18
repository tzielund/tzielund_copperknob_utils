"""Beat Tapper — Guitar-Hero-style beat aptitude test (builder + library).

Maintains a library of analyzed songs that are played by a single standalone
HTML page (`beat_tapper_html/beat_tapper.html`, copied from
`beat_tapper_player.html` at the repo root).

Per song, three files live in `beat_tapper_html/library/`:
    {slug}.mp3    original audio (so we can re-load it for curation)
    {slug}.json   editable source of truth: title, BASE beats, intro/outro skip,
                  double_time flag, notes
    {slug}.js     generated: calls window.CK_LOAD(slug, {...}) with base64 audio
                  and the EFFECTIVE beats (BASE doubled if double_time is on)
And one shared file:
    index.js      window.CK_SONGS = [{slug, title, bpm, beats_count, duration, notes}, ...]

Builder modes:
    New from audio  — upload or pick an MP3, run librosa, curate beats, save
    Edit existing   — load a library song, adjust metadata or beats, re-save
    Delete          — drop a song from the library

Beat curation is a textarea (one timestamp per line) plus a "Preview with
audible clicks" button that mixes click track into the song so you can hear
whether the current timings line up with the music. librosa's beat tracker
tends to lose the plot on songs with tempo changes — manual curation is the
escape hatch.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
import streamlit as st

OUTPUT_DIR     = Path("beat_tapper_html")
LIBRARY_DIR    = OUTPUT_DIR / "library"
PLAYER_SRC     = Path("beat_tapper_player.html")
PLAYER_DEST    = OUTPUT_DIR / "beat_tapper.html"
RECORDER_SRC   = Path("beat_tapper_recorder.html")
RECORDER_DEST  = OUTPUT_DIR / "beat_tapper_recorder.html"

MIME_BY_EXT = {
    ".mp3":  "audio/mpeg",
    ".wav":  "audio/wav",
    ".m4a":  "audio/mp4",
    ".ogg":  "audio/ogg",
    ".flac": "audio/flac",
}


# ─── helpers ─────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return s[:80] or "song"


def guess_mime(path: str | Path) -> str:
    return MIME_BY_EXT.get(Path(path).suffix.lower(), "audio/mpeg")


_SPOTIFY_TRACK_ID_RE = re.compile(r"(?:spotify:track:|open\.spotify\.com/track/|^)([A-Za-z0-9]{22})")

def normalize_spotify_uri(raw: str) -> str:
    """Return a `spotify:track:ID` URI, or '' if nothing recognizable.

    Accepts any of:
      spotify:track:5Jt4Mt2TI4t2T8w3Uc4Mn7
      https://open.spotify.com/track/5Jt4Mt2TI4t2T8w3Uc4Mn7?si=abc
      5Jt4Mt2TI4t2T8w3Uc4Mn7
    """
    if not raw:
        return ""
    m = _SPOTIFY_TRACK_ID_RE.search(raw.strip())
    if not m:
        return ""
    return "spotify:track:" + m.group(1)


def parse_beats_text(text: str) -> tuple[list[float], list[str]]:
    """Parse one-time-per-line beats text. Returns (beats_sorted, errors)."""
    beats: list[float] = []
    errors: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            beats.append(float(s))
        except ValueError:
            errors.append(f"Line {i}: {s!r} is not a number")
    return sorted(beats), errors


def format_beats_text(beats: list[float]) -> str:
    return "\n".join(f"{t:.4f}" for t in beats)


def apply_double_time(beats: list[float]) -> list[float]:
    """Insert a midpoint between every consecutive pair. N → 2N-1.

    Fixes songs where librosa latches onto a half-time pulse (e.g. two-step
    tracked slow-slow instead of quick-quick-slow-slow).
    """
    if len(beats) < 2:
        return list(beats)
    out: list[float] = []
    for i in range(len(beats) - 1):
        out.append(beats[i])
        out.append((beats[i] + beats[i + 1]) / 2.0)
    out.append(beats[-1])
    return out


def _audio_cache_key(mp3_path: Path) -> str:
    st_ = mp3_path.stat()
    return f"{mp3_path.resolve()}::{st_.st_mtime_ns}::{st_.st_size}"


@st.cache_data(show_spinner=False)
def _load_audio_cached(key: str, path_str: str) -> tuple[np.ndarray, int]:
    y, sr = librosa.load(path_str, sr=None, mono=True)
    return y, sr


def load_audio(mp3_path: Path) -> tuple[np.ndarray, int]:
    return _load_audio_cached(_audio_cache_key(mp3_path), str(mp3_path))


def detect_beats(y: np.ndarray, sr: int) -> tuple[float, list[float]]:
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beats = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    bpm = float(np.ravel(tempo)[0])
    return bpm, beats


def click_preview_bytes(
    y: np.ndarray,
    sr: int,
    beats: list[float],
    measures: list[float] | None = None,
    phrases: list[float] | None = None,
) -> bytes:
    """Return a WAV byte string of y + three-tier click track.

    Each list should be a subset of `beats`. Phrase clicks are highest-pitched
    and loudest, measure clicks are a middle tier, regular beats are lowest.
    The function removes overlaps so each time gets exactly one click at its
    tier's volume + pitch.
    """
    phrase_set  = set(phrases  or [])
    measure_set = set(measures or []) - phrase_set
    regular     = [t for t in beats if t not in phrase_set and t not in measure_set]
    layers = []
    if regular:
        layers.append(0.5 * librosa.clicks(
            times=np.asarray(regular), sr=sr, length=len(y), click_freq=1000.0,
        ))
    if measure_set:
        layers.append(0.6 * librosa.clicks(
            times=np.asarray(sorted(measure_set)), sr=sr, length=len(y), click_freq=1300.0,
        ))
    if phrase_set:
        layers.append(0.75 * librosa.clicks(
            times=np.asarray(sorted(phrase_set)), sr=sr, length=len(y), click_freq=1700.0,
        ))
    if not layers:
        mix = y
    else:
        mix = 0.6 * y
        for layer in layers:
            mix = mix + layer
        mix = mix / max(1e-9, float(np.max(np.abs(mix))))
    import io
    buf = io.BytesIO()
    sf.write(buf, mix, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def period_indices(
    n_effective: int,
    intro_skip: int,
    outro_skip: int,
    period: int,
    offset: int,
) -> list[int]:
    """Indices into the full effective-beats list that land on the period.

    The first index sits `offset` beats after `intro_skip`; subsequent indices
    are spaced `period` beats apart; none fall inside the outro. Used for both
    measure-1s and phrase-1s.
    """
    if period < 1 or n_effective <= 0:
        return []
    start = int(intro_skip) + int(offset)
    end = n_effective - int(outro_skip)
    return list(range(start, end, int(period)))


# ─── library I/O ─────────────────────────────────────────────────────────────

def library_slugs() -> list[str]:
    if not LIBRARY_DIR.exists():
        return []
    return sorted(p.stem for p in LIBRARY_DIR.glob("*.json"))


def load_song_record(slug: str) -> dict | None:
    p = LIBRARY_DIR / f"{slug}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def find_audio_for(slug: str) -> Path | None:
    for ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac"):
        p = LIBRARY_DIR / f"{slug}{ext}"
        if p.exists():
            return p
    return None


def save_song(
    slug: str,
    *,
    source_audio: Path,
    title: str,
    bpm: float,
    duration: float,
    beats: list[float],
    intro_skip: int,
    outro_skip: int,
    notes: str,
    double_time: bool = False,
    measure_period: int = 4,
    phrase_period: int = 8,
    phrase_offset: int = 0,
    spotify_track_uri: str = "",
) -> None:
    """Writes {slug}.mp3 (if new), {slug}.json, {slug}.js, and regenerates index.js.

    `beats` is the BASE beat list (as shown in the textarea). The generated
    {slug}.js receives the EFFECTIVE list (doubled when double_time is True)
    so the player doesn't need to know about the flag. Period/offset values
    are stored as-is; the player and recorder derive the actual indices from
    them at load time. Measures use the same offset as phrases, so the first
    beat of each phrase is also the first beat of its measure.
    """
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    ext = source_audio.suffix.lower()
    audio_dest = LIBRARY_DIR / f"{slug}{ext}"
    if source_audio.resolve() != audio_dest.resolve():
        shutil.copyfile(source_audio, audio_dest)

    base_beats = [round(t, 4) for t in beats]
    effective_beats = apply_double_time(base_beats) if double_time else base_beats

    record = {
        "slug":              slug,
        "title":             title,
        "bpm":               round(bpm, 2),
        "duration":          round(duration, 3),
        "intro_skip":        int(intro_skip),
        "outro_skip":        int(outro_skip),
        "double_time":       bool(double_time),
        "measure_period":    int(measure_period),
        "phrase_period":     int(phrase_period),
        "phrase_offset":     int(phrase_offset),
        "spotify_track_uri": normalize_spotify_uri(spotify_track_uri),
        "notes":             notes,
        "beats":             base_beats,
        "audio_ext":         ext,
    }
    (LIBRARY_DIR / f"{slug}.json").write_text(json.dumps(record, indent=2))

    audio_b64 = base64.b64encode(audio_dest.read_bytes()).decode("ascii")
    js_payload = {
        "title":          title,
        "bpm":            record["bpm"],
        "duration":       record["duration"],
        "beats":          effective_beats,
        "intro_skip":     record["intro_skip"],
        "outro_skip":     record["outro_skip"],
        "measure_period": record["measure_period"],
        "phrase_period":  record["phrase_period"],
        "phrase_offset":  record["phrase_offset"],
        "spotify_uri":    record["spotify_track_uri"],
        "notes":          notes,
        "audio_mime":     guess_mime(audio_dest),
        "audio_b64":      audio_b64,
    }
    js_literal = json.dumps(js_payload)
    js_text = (
        f"window.CK_LOAD({json.dumps(slug)}, {js_literal});\n"
    )
    (LIBRARY_DIR / f"{slug}.js").write_text(js_text)

    rebuild_index()
    ensure_player()


def rebuild_index() -> None:
    entries = []
    for slug in library_slugs():
        rec = load_song_record(slug)
        if not rec:
            continue
        base = rec["beats"]
        effective = apply_double_time(base) if rec.get("double_time") else base
        entries.append({
            "slug":        rec["slug"],
            "title":       rec["title"],
            "bpm":         rec["bpm"],
            "duration":    rec["duration"],
            "beats_count": len(effective),
            "notes":       rec.get("notes", ""),
            "has_spotify": bool(rec.get("spotify_track_uri", "")),
        })
    # Sort by title (case-insensitive)
    entries.sort(key=lambda e: e["title"].lower())
    js = "window.CK_SONGS = " + json.dumps(entries, indent=2) + ";\n"
    (LIBRARY_DIR / "index.js").write_text(js)


def _copy_if_stale(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def ensure_player() -> None:
    _copy_if_stale(PLAYER_SRC, PLAYER_DEST)
    _copy_if_stale(RECORDER_SRC, RECORDER_DEST)


def build_phone_bundle(slugs: list[str]) -> tuple[Path, int]:
    """Bundle the player + selected songs into one self-contained HTML.

    Returns (output_path, size_bytes). The resulting file can be AirDropped,
    emailed, or dropped into iCloud Drive; opening it on a phone loads
    everything from a single document with no server or sidecar files.

    Implementation: grabs each song's generated `.js` (which already contains
    the base64 audio + effective beats) and injects them into the player's
    HTML as a bundled bootstrap. The player checks `window.CK_BUNDLED` at
    startup and skips its usual dynamic library/*.js load.
    """
    player_html = PLAYER_SRC.read_text()

    entries = []
    preload: dict[str, dict] = {}
    for slug in slugs:
        rec = load_song_record(slug)
        if not rec:
            continue
        audio_src = find_audio_for(slug)
        if not audio_src:
            continue
        base = rec["beats"]
        effective = apply_double_time(base) if rec.get("double_time") else base
        entries.append({
            "slug":        rec["slug"],
            "title":       rec["title"],
            "bpm":         rec["bpm"],
            "duration":    rec["duration"],
            "beats_count": len(effective),
            "notes":       rec.get("notes", ""),
            "has_spotify": bool(rec.get("spotify_track_uri", "")),
        })
        audio_b64 = base64.b64encode(audio_src.read_bytes()).decode("ascii")
        preload[slug] = {
            "title":          rec["title"],
            "bpm":            rec["bpm"],
            "duration":       rec["duration"],
            "beats":          effective,
            "intro_skip":     rec.get("intro_skip", 0),
            "outro_skip":     rec.get("outro_skip", 0),
            "measure_period": rec.get("measure_period", 4),
            "phrase_period":  rec.get("phrase_period", rec.get("downbeat_period", 8)),
            "phrase_offset":  rec.get("phrase_offset", rec.get("downbeat_offset", 0)),
            "spotify_uri":    rec.get("spotify_track_uri", ""),
            "notes":          rec.get("notes", ""),
            "audio_mime":     guess_mime(audio_src),
            "audio_b64":      audio_b64,
        }

    entries.sort(key=lambda e: e["title"].lower())

    bootstrap = (
        "<script>\n"
        "window.CK_BUNDLED = true;\n"
        "window.CK_SONGS = " + json.dumps(entries) + ";\n"
        "window.CK_PRELOAD = " + json.dumps(preload) + ";\n"
        "</script>\n"
    )
    # Inject right after <body> so it runs before the main player script
    # defines CK_LOAD — the init IIFE at the bottom will honor CK_BUNDLED.
    if "<body>" not in player_html:
        raise RuntimeError("Could not find <body> in player HTML.")
    bundled = player_html.replace("<body>", "<body>\n" + bootstrap, 1)

    out = OUTPUT_DIR / "beat_tapper_phone.html"
    out.write_text(bundled)
    return out, out.stat().st_size


def merge_taps(detected: list[float], taps: list[float], proximity: float) -> tuple[list[float], int]:
    """Apply tap overrides to a detected beat list.

    Any detected beat within `proximity` seconds of ANY tap is dropped, then
    the tap times are added back in. Detected beats far from every tap are
    kept — so a short tap-along section only overrides the beats in that
    stretch of the song.

    Returns (merged_beats_sorted, dropped_count).
    """
    if not taps:
        return sorted(detected), 0
    sorted_taps = sorted(taps)
    kept = []
    dropped = 0
    # Linear two-pointer scan — both lists are sorted
    j = 0
    for b in sorted(detected):
        # Advance the tap pointer past any taps that are below b - proximity
        while j < len(sorted_taps) and sorted_taps[j] < b - proximity:
            j += 1
        # Check if any tap is within proximity of this beat
        if j < len(sorted_taps) and sorted_taps[j] <= b + proximity:
            dropped += 1
        else:
            kept.append(b)
    return sorted(kept + sorted_taps), dropped


def delete_song(slug: str) -> None:
    for p in LIBRARY_DIR.glob(f"{slug}.*"):
        p.unlink()
    rebuild_index()


# ─── UI ──────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Beat Tapper Builder", layout="wide")
st.title("Beat Tapper — library builder")
st.caption(
    "Analyze songs with librosa, curate the beat timings, and save them into a "
    "library that the standalone player (`beat_tapper_html/beat_tapper.html`) "
    "can load from a song picker. The player is file://-friendly — no server "
    "needed — because song data is loaded as `<script>` tags, not fetched JSON."
)

if not PLAYER_SRC.exists():
    st.error(f"Missing `{PLAYER_SRC}` at the repo root — can't build the player.")
    st.stop()

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
ensure_player()

# ─── Links to the standalone HTML pages ──────────────────────────────────────
# Browsers block file:// links from http://localhost pages, so we show the
# URL plus a copy-paste `open` command. Both work on macOS; the URL is also
# clickable if you paste it into the address bar.

player_url   = PLAYER_DEST.resolve().as_uri()    # file:///...
recorder_url = RECORDER_DEST.resolve().as_uri()

L1, L2 = st.columns(2)
with L1:
    st.markdown(f"**[Open Player]({player_url})** — tap along to score yourself")
    st.code(f"open '{PLAYER_DEST.resolve()}'", language="bash")
with L2:
    st.markdown(f"**[Open Recorder]({recorder_url})** — curate beats by tapping")
    st.code(f"open '{RECORDER_DEST.resolve()}'", language="bash")

st.divider()

existing = library_slugs()
mode = st.radio(
    "Mode",
    ["New from audio", "Edit existing", "Delete"],
    horizontal=True,
    disabled=False,
)

# ─── pick the working slug + source audio for this run ───────────────────────

audio_path: Path | None = None
record: dict | None = None
working_slug: str | None = None

if mode == "New from audio":
    src = st.radio("Audio source", ["Upload file", "Path on disk"], horizontal=True)
    if src == "Upload file":
        up = st.file_uploader("Audio file", type=list(MIME_BY_EXT.keys()))
        if up:
            # Stage into LIBRARY_DIR under a provisional slug; user confirms title before save.
            prov_slug = slugify(Path(up.name).stem)
            tmp = LIBRARY_DIR / f"_stage_{prov_slug}{Path(up.name).suffix.lower()}"
            tmp.write_bytes(up.read())
            audio_path = tmp
    else:
        p = st.text_input("Absolute path", placeholder="/Users/you/Music/song.mp3")
        if p:
            pp = Path(p).expanduser()
            if pp.exists():
                audio_path = pp
            else:
                st.error(f"Not found: {pp}")

elif mode == "Edit existing":
    if not existing:
        st.info("Library is empty. Switch to **New from audio** to add a song first.")
        st.stop()
    working_slug = st.selectbox("Song in library", existing)
    record = load_song_record(working_slug)
    audio_path = find_audio_for(working_slug)
    if not audio_path:
        st.error(f"Audio file for `{working_slug}` missing from `{LIBRARY_DIR}`.")
        st.stop()

elif mode == "Delete":
    if not existing:
        st.info("Library is empty.")
        st.stop()
    target = st.selectbox("Song to delete", existing)
    rec = load_song_record(target) or {}
    st.warning(f"Will remove `{target}.*` from the library "
               f"(title: *{rec.get('title','?')}*).")
    if st.button("Delete permanently", type="primary"):
        delete_song(target)
        st.success(f"Deleted `{target}` and regenerated the index.")
        st.rerun()
    st.stop()

if audio_path is None:
    st.stop()

# ─── session state keyed by audio path ───────────────────────────────────────

state_key = f"bt_state::{audio_path.resolve()}"
if state_key not in st.session_state:
    # Seed from the library record if editing; otherwise detect fresh.
    with st.spinner("Loading audio…"):
        y, sr = load_audio(audio_path)
    duration = float(len(y)) / float(sr)
    if record:
        bpm, beats = record["bpm"], list(record["beats"])
    else:
        with st.spinner("Detecting beats…"):
            bpm, beats = detect_beats(y, sr)
    st.session_state[state_key] = {
        "sr":       sr,
        "duration": duration,
        "bpm":      bpm,
        "beats":    beats,
    }

sess = st.session_state[state_key]

# ─── Metadata ────────────────────────────────────────────────────────────────

st.subheader("Metadata")
default_title = (record and record["title"]) or audio_path.stem.replace("_", " ")
title = st.text_input("Title (shown in the picker and the game)", value=default_title)
slug  = working_slug or slugify(title)
st.caption(f"Slug: `{slug}` — this becomes the library file stem.")

col_i, col_o = st.columns(2)
default_intro = (record and record.get("intro_skip", 0)) or 0
default_outro = (record and record.get("outro_skip", 0)) or 0
# Generous cap: covers the double-time case (2N-1) and a bit of manual slack.
skip_cap = max(1, 2 * len(sess["beats"]) - 1)
intro_skip = col_i.number_input(
    "Intro beats to skip",
    min_value=0, max_value=skip_cap,
    value=int(default_intro), step=1,
    help=("The first N effective beats won't be scored. Useful for tracks "
          "with a metered intro, drum fill, or pickup beats."),
)
outro_skip = col_o.number_input(
    "Outro beats to skip",
    min_value=0, max_value=skip_cap,
    value=int(default_outro), step=1,
    help="The last N effective beats won't be scored (ritard, fade-out, etc.).",
)
default_double = bool(record.get("double_time", False)) if record else False
double_time = st.checkbox(
    "Double-time (insert midpoint between each consecutive pair of beats)",
    value=default_double,
    key=f"bt_double::{audio_path.resolve()}",
    help=("Toggle when librosa latches onto a half-time pulse — e.g. a "
          "two-step tracked slow-slow instead of quick-quick-slow-slow. "
          "The textarea still shows the base beats; the player and preview "
          "use the doubled series. Persists in the saved record."),
)

col_mp, col_pp, col_po = st.columns(3)
# Backward-compat: honor the old downbeat_period/offset field names if present.
default_measure = int(record.get("measure_period", 4)) if record else 4
default_phrase  = int(record.get("phrase_period",
                                 record.get("downbeat_period", 8))) if record else 8
default_phr_off = int(record.get("phrase_offset",
                                 record.get("downbeat_offset", 0))) if record else 0
measure_period = col_mp.number_input(
    "Measure period",
    min_value=1, max_value=16,
    value=max(1, default_measure), step=1,
    help=("Beats per measure. 4 for most 4/4 music, 3 for waltz, "
          "2 for a two-step cell. Measure 1 gets a small accent in the "
          "player and a medium click in the preview."),
)
phrase_period = col_pp.number_input(
    "Phrase period",
    min_value=1, max_value=64,
    value=max(1, default_phrase), step=1,
    help=("Beats per phrase (i.e. the dancer's '1'). 8 suits most "
          "32-count line dances; 48 or 24 for waltz; 16/32 for long phrases."),
)
phrase_offset = col_po.number_input(
    "Phrase offset",
    min_value=0, max_value=max(0, int(phrase_period) - 1),
    value=min(default_phr_off, max(0, int(phrase_period) - 1)), step=1,
    help=("Which effective beat (after intro skip) is the FIRST phrase 1. "
          "0 means the first non-intro beat is the phrase 1, which is "
          "almost always right. Measures use the same offset."),
)

notes_val = st.text_area(
    "Notes (free-form; shown as a caption in the song picker)",
    value=(record and record.get("notes", "")) or "",
    height=80,
)

spotify_val_raw = st.text_input(
    "Spotify track (URI, open.spotify.com URL, or 22-char ID)",
    value=(record and record.get("spotify_track_uri", "")) or "",
    placeholder="spotify:track:5Jt4Mt2TI4t2T8w3Uc4Mn7  (or paste a share link)",
    help=("Optional. When set AND the player is signed in to Spotify Premium, "
          "playback streams from Spotify instead of the bundled audio. Beat "
          "timing is read from the Spotify SDK position; no new beat analysis "
          "is needed."),
)
spotify_val = normalize_spotify_uri(spotify_val_raw)
if spotify_val_raw and not spotify_val:
    st.warning("Couldn't find a Spotify track ID in that string — leaving blank.")
elif spotify_val:
    st.caption(f"Normalized → `{spotify_val}`")

# ─── Beats curator ───────────────────────────────────────────────────────────

st.subheader("Beats curator")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Tempo",    f"{sess['bpm']:.1f} BPM" + (" ×2" if double_time else ""))
c2.metric("Beats (detected base)", f"{len(sess['beats'])}")
c3.metric("Duration", f"{sess['duration']:.1f} s")
_effective_count = len(apply_double_time(sess["beats"])) if double_time else len(sess["beats"])
_meas_count = len(period_indices(
    _effective_count, int(intro_skip), int(outro_skip),
    int(measure_period), int(phrase_offset),
))
_phr_count = len(period_indices(
    _effective_count, int(intro_skip), int(outro_skip),
    int(phrase_period), int(phrase_offset),
))
c4.metric("Measures", f"{_meas_count}",
          help=f"every {int(measure_period)} effective beats starting at offset {int(phrase_offset)}")
c5.metric("Phrases", f"{_phr_count}",
          help=f"every {int(phrase_period)} effective beats starting at offset {int(phrase_offset)}")

st.caption(
    "One beat timestamp per line, in seconds. Edit, add, or remove lines to "
    "fix the detection. librosa struggles with tempo changes — manual is the "
    "escape hatch. Lines starting with `#` are comments."
)

beats_text_key = f"bt_text::{audio_path.resolve()}"
beats_pending_key = f"bt_text_pending::{audio_path.resolve()}"

# Consume any pending update from a prior button press (merge / nudge / re-detect).
# Must run BEFORE the text_area is instantiated — Streamlit forbids mutating a
# widget's session_state key after the widget has rendered in the same run.
if beats_pending_key in st.session_state:
    st.session_state[beats_text_key] = st.session_state.pop(beats_pending_key)

if beats_text_key not in st.session_state:
    st.session_state[beats_text_key] = format_beats_text(sess["beats"])

beats_text = st.text_area(
    "Beat times (seconds)",
    key=beats_text_key,
    height=260,
)
parsed_beats, parse_errors = parse_beats_text(beats_text)
effective_beats = apply_double_time(parsed_beats) if double_time else parsed_beats
if parse_errors:
    st.warning("Parse issues — fix before saving:\n\n" + "\n".join(f"- {e}" for e in parse_errors))
else:
    if double_time:
        st.caption(
            f"✔ parsed {len(parsed_beats)} base beats → "
            f"**{len(effective_beats)} effective beats** (double-time on)"
        )
    else:
        st.caption(f"✔ parsed {len(parsed_beats)} beats")

tool_cols = st.columns(4)
if tool_cols[0].button("Re-detect from audio (overwrites)"):
    with st.spinner("Re-running beat_track…"):
        y, sr = load_audio(audio_path)
        bpm, beats = detect_beats(y, sr)
    sess["bpm"] = bpm
    sess["beats"] = beats
    st.session_state[beats_pending_key] = format_beats_text(beats)
    st.rerun()

nudge_ms = tool_cols[1].number_input("Nudge all (ms)", value=0, step=5)
if tool_cols[2].button("Apply nudge"):
    if nudge_ms and not parse_errors:
        shifted = [t + nudge_ms / 1000.0 for t in parsed_beats]
        st.session_state[beats_pending_key] = format_beats_text(shifted)
        st.rerun()

if tool_cols[3].button("Preview with audible clicks", disabled=bool(parse_errors)):
    # Click only the EFFECTIVE beats that will actually be scored — doubled
    # if the flag is on, then with intro/outro slices applied, so the preview
    # matches what the player will do. Measure-1s get a mid-pitched click,
    # phrase-1s get a higher-pitched/louder click.
    scored = effective_beats[int(intro_skip) : len(effective_beats) - int(outro_skip)]
    meas_idxs = period_indices(
        len(effective_beats), int(intro_skip), int(outro_skip),
        int(measure_period), int(phrase_offset),
    )
    phr_idxs = period_indices(
        len(effective_beats), int(intro_skip), int(outro_skip),
        int(phrase_period), int(phrase_offset),
    )
    meas_times = [effective_beats[i] for i in meas_idxs]
    phr_times  = [effective_beats[i] for i in phr_idxs]
    with st.spinner(
        f"Rendering click preview ({len(scored)} beats, "
        f"{len(meas_times)} measures, {len(phr_times)} phrases)…"
    ):
        y, sr = load_audio(audio_path)
        wav = click_preview_bytes(y, sr, scored, measures=meas_times, phrases=phr_times)
    dt_note = " (double-time on)" if double_time else ""
    st.caption(
        f"Clicks on beats {int(intro_skip) + 1}–{len(effective_beats) - int(outro_skip)} "
        f"of {len(effective_beats)} effective"
        f"{dt_note} (intro skip {int(intro_skip)}, outro skip {int(outro_skip)}). "
        f"Measure-1s: {len(meas_times)} (mid pitch). "
        f"Phrase-1s: {len(phr_times)} (high pitch, loudest)."
    )
    st.audio(wav, format="audio/wav")

# ─── Tap-along import ───────────────────────────────────────────────────────

st.divider()
st.subheader("Import tap recording")
st.caption(
    "Use the recorder page to tap along with the song, then import the "
    "downloaded JSON here. Detected beats within **proximity** seconds of "
    "any tap are replaced by the tap times; beats far from every tap are "
    "left alone, so a short tap-along only overrides the section you "
    "actually tapped through."
)

if RECORDER_DEST.exists():
    st.markdown(f"Launch the [recorder]({recorder_url}) (link also at the top of the page).")
else:
    st.info("Recorder HTML not yet copied — click **Save to library** once to copy it into place.")

tap_file = st.file_uploader("Taps JSON (from the recorder)", type=["json"], key="tap_json_upload")
if tap_file is not None:
    try:
        tap_data = json.loads(tap_file.read())
    except Exception as e:
        st.error(f"Could not parse JSON: {e}")
    else:
        rec_slug  = tap_data.get("slug", "?")
        rec_title = tap_data.get("song_title", "?")
        all_taps  = [float(t) for t in tap_data.get("all_taps", [])]
        regions   = tap_data.get("regions", [])

        cI, cR, cT = st.columns(3)
        cI.metric("Taps",    len(all_taps))
        cR.metric("Regions", len(regions))
        cT.metric("For slug", rec_slug)

        if rec_slug and rec_slug != slug:
            st.warning(
                f"Slug mismatch: this recording is for `{rec_slug}` "
                f"(*{rec_title}*), but you're editing `{slug}`. "
                "Merging anyway if you continue."
            )

        proximity = st.slider(
            "Proximity (seconds)",
            min_value=0.05, max_value=1.00, value=0.30, step=0.05,
            help=("A detected beat within this many seconds of any tap is "
                  "replaced by the tap. Use about half the beat interval: "
                  "~0.3s suits 100 BPM; drop to ~0.2s for 150+ BPM."),
        )

        if all_taps and not parse_errors:
            merged, dropped = merge_taps(parsed_beats, all_taps, proximity)
            delta = len(merged) - len(parsed_beats)
            st.caption(
                f"Merge preview: {len(parsed_beats)} current beats → "
                f"{len(merged)} after merge · {dropped} detected beats displaced · "
                f"{len(all_taps)} taps added (net {delta:+d})."
            )
            with st.expander(f"Regions in this recording ({len(regions)})"):
                if regions:
                    for i, r in enumerate(regions, 1):
                        st.write(
                            f"**#{i}** — {r['start']:.2f}s → {r['end']:.2f}s "
                            f"({len(r.get('taps', []))} taps)"
                        )
                else:
                    st.write("_No regions in this recording._")

            if st.button("Apply merge to beats textarea"):
                st.session_state[beats_pending_key] = format_beats_text(merged)
                st.success(
                    f"Merged {len(all_taps)} taps into the beats list. "
                    "Scroll up to review, then **Save to library**."
                )
                st.rerun()
        elif not all_taps:
            st.info("Recording has no taps — nothing to merge.")


# ─── Save ────────────────────────────────────────────────────────────────────

st.divider()
st.subheader("Save to library")

can_save = not parse_errors and len(parsed_beats) > 0 and title.strip() != ""
if not can_save:
    st.info("Fix any parse issues and give the song a title to enable saving.")

if st.button("Save to library", type="primary", disabled=not can_save):
    # Figure out the real source audio file to copy from. If we staged an upload,
    # move/copy that into its final name on save.
    if audio_path.name.startswith("_stage_"):
        final_audio = LIBRARY_DIR / f"{slug}{audio_path.suffix.lower()}"
        shutil.move(str(audio_path), final_audio)
        source_for_save = final_audio
    else:
        source_for_save = audio_path

    save_song(
        slug,
        source_audio=source_for_save,
        title=title.strip(),
        bpm=sess["bpm"],
        duration=sess["duration"],
        beats=parsed_beats,
        intro_skip=int(intro_skip),
        outro_skip=int(outro_skip),
        notes=notes_val.strip(),
        double_time=bool(double_time),
        measure_period=int(measure_period),
        phrase_period=int(phrase_period),
        phrase_offset=int(phrase_offset),
        spotify_track_uri=spotify_val,
    )
    eff_count = len(apply_double_time(parsed_beats)) if double_time else len(parsed_beats)
    meas_saved = len(period_indices(
        eff_count, int(intro_skip), int(outro_skip),
        int(measure_period), int(phrase_offset),
    ))
    phr_saved = len(period_indices(
        eff_count, int(intro_skip), int(outro_skip),
        int(phrase_period), int(phrase_offset),
    ))
    st.success(
        f"Saved `{slug}` ({len(parsed_beats)} base → {eff_count} effective beats, "
        f"intro skip {intro_skip}, outro skip {outro_skip}"
        f"{', double-time ON' if double_time else ''}, "
        f"{meas_saved} measures every {int(measure_period)}, "
        f"{phr_saved} phrases every {int(phrase_period)})."
    )
    st.code(f"open '{PLAYER_DEST.resolve()}'", language="bash")
    st.caption(
        f"Library now holds {len(library_slugs())} song(s). "
        f"The player picks them up from `library/index.js` on next load."
    )


# ─── Phone bundle ────────────────────────────────────────────────────────────

st.divider()
st.subheader("Build phone bundle")
st.caption(
    "Bundle the player and selected songs into one self-contained HTML — "
    "no sidecar files, no server. AirDrop / email / drop in iCloud Drive, "
    "then open on the phone. Figure ~7 MB per minute of audio."
)

bundle_slugs = library_slugs()
if not bundle_slugs:
    st.info("Library is empty — save at least one song to build a bundle.")
else:
    # Size estimate from on-disk audio
    size_hint = {}
    for s in bundle_slugs:
        a = find_audio_for(s)
        if a:
            # base64 overhead ≈ 4/3, plus JSON/HTML scaffolding
            size_hint[s] = int(a.stat().st_size * 1.35)

    def _label(slug: str) -> str:
        rec = load_song_record(slug) or {}
        mb = size_hint.get(slug, 0) / 1_048_576
        return f"{rec.get('title', slug)}  (~{mb:.1f} MB)"

    picked = st.multiselect(
        "Songs to include",
        options=bundle_slugs,
        default=bundle_slugs,
        format_func=_label,
    )
    est_mb = sum(size_hint.get(s, 0) for s in picked) / 1_048_576
    st.caption(f"Estimated bundle size: **~{est_mb:.1f} MB** "
               f"({len(picked)} song{'' if len(picked) == 1 else 's'}).")

    if st.button("Build bundle", type="primary", disabled=not picked):
        with st.spinner(f"Bundling {len(picked)} song(s)…"):
            out, size = build_phone_bundle(picked)
        st.success(
            f"Wrote `{out.resolve()}` ({size / 1_048_576:.1f} MB). "
            "AirDrop or email it to the phone and open in Safari / Chrome."
        )
        st.code(f"open -R '{out.resolve()}'  # reveal in Finder for AirDrop", language="bash")
