"""Beat Tapper — Guitar-Hero-style beat aptitude test (builder + library).

Maintains a library of analyzed songs that are played by a single standalone
HTML page (`beat_tapper_html/beat_tapper.html`, copied from
`beat_tapper_player.html` at the repo root).

Per song, three files live in `beat_tapper_html/library/`:
    {slug}.mp3    original audio (so we can re-load it for curation)
    {slug}.json   editable source of truth: title, beats, intro/outro skip, notes
    {slug}.js     generated: calls window.CK_LOAD(slug, {...}) with base64 audio
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


def click_preview_bytes(y: np.ndarray, sr: int, beats: list[float]) -> bytes:
    """Return a WAV byte string of y + click track at `beats`."""
    if not beats:
        mix = y
    else:
        clicks = librosa.clicks(times=np.asarray(beats), sr=sr, length=len(y))
        mix = 0.6 * y + 0.5 * clicks
        mix = mix / max(1e-9, float(np.max(np.abs(mix))))
    import io
    buf = io.BytesIO()
    sf.write(buf, mix, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


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
) -> None:
    """Writes {slug}.mp3 (if new), {slug}.json, {slug}.js, and regenerates index.js."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    ext = source_audio.suffix.lower()
    audio_dest = LIBRARY_DIR / f"{slug}{ext}"
    if source_audio.resolve() != audio_dest.resolve():
        shutil.copyfile(source_audio, audio_dest)

    record = {
        "slug":        slug,
        "title":       title,
        "bpm":         round(bpm, 2),
        "duration":    round(duration, 3),
        "intro_skip":  int(intro_skip),
        "outro_skip":  int(outro_skip),
        "notes":       notes,
        "beats":       [round(t, 4) for t in beats],
        "audio_ext":   ext,
    }
    (LIBRARY_DIR / f"{slug}.json").write_text(json.dumps(record, indent=2))

    audio_b64 = base64.b64encode(audio_dest.read_bytes()).decode("ascii")
    js_payload = {
        "title":       title,
        "bpm":         record["bpm"],
        "duration":    record["duration"],
        "beats":       record["beats"],
        "intro_skip":  record["intro_skip"],
        "outro_skip":  record["outro_skip"],
        "notes":       notes,
        "audio_mime":  guess_mime(audio_dest),
        "audio_b64":   audio_b64,
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
        entries.append({
            "slug":        rec["slug"],
            "title":       rec["title"],
            "bpm":         rec["bpm"],
            "duration":    rec["duration"],
            "beats_count": len(rec["beats"]),
            "notes":       rec.get("notes", ""),
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
intro_skip = col_i.number_input(
    "Intro beats to skip",
    min_value=0, max_value=max(1, len(sess["beats"]) - 1),
    value=int(default_intro), step=1,
    help=("The first N detected beats won't be scored. Useful for tracks with "
          "a metered intro, drum fill, or pickup beats."),
)
outro_skip = col_o.number_input(
    "Outro beats to skip",
    min_value=0, max_value=max(1, len(sess["beats"]) - 1),
    value=int(default_outro), step=1,
    help="The last N detected beats won't be scored (ritard, fade-out, etc.).",
)
notes_val = st.text_area(
    "Notes (free-form; shown as a caption in the song picker)",
    value=(record and record.get("notes", "")) or "",
    height=80,
)

# ─── Beats curator ───────────────────────────────────────────────────────────

st.subheader("Beats curator")
c1, c2, c3 = st.columns(3)
c1.metric("Tempo",    f"{sess['bpm']:.1f} BPM")
c2.metric("Beats",    f"{len(sess['beats'])}")
c3.metric("Duration", f"{sess['duration']:.1f} s")

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
if parse_errors:
    st.warning("Parse issues — fix before saving:\n\n" + "\n".join(f"- {e}" for e in parse_errors))
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
    # Click only the beats that will actually be scored — skipping intro/outro
    # so the preview matches what the player will do.
    scored = parsed_beats[int(intro_skip) : len(parsed_beats) - int(outro_skip)]
    with st.spinner(f"Rendering click preview ({len(scored)} clicks)…"):
        y, sr = load_audio(audio_path)
        wav = click_preview_bytes(y, sr, scored)
    st.caption(
        f"Clicks on beats {int(intro_skip) + 1}–{len(parsed_beats) - int(outro_skip)} "
        f"of {len(parsed_beats)} (intro skip {int(intro_skip)}, outro skip {int(outro_skip)})."
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
    st.markdown(
        f"**Recorder:** `{RECORDER_DEST.resolve()}` — "
        f"`open '{RECORDER_DEST.resolve()}'` in a terminal to launch it."
    )
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
    )
    st.success(
        f"Saved `{slug}` ({len(parsed_beats)} beats, intro skip {intro_skip}, "
        f"outro skip {outro_skip})."
    )
    st.code(f"open '{PLAYER_DEST.resolve()}'", language="bash")
    st.caption(
        f"Library now holds {len(library_slugs())} song(s). "
        f"The player picks them up from `library/index.js` on next load."
    )
