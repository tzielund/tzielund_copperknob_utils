"""Open Watermelon-Crawl.mid, apply modifications, write a new MIDI file."""

import pandas
import mido
import streamlit

INPUT_PATH = "Watermelon-Crawl.mid"
OUTPUT_PATH = "Watermelon-Crawl-modified.mid"

# Spots where a 2-beat hold is inserted. Expressed as (bar, beat) in GarageBand convention
# where "beat 5" in 4/4 means the position at the start of the next bar.
INSERTION_POINTS_BAR_BEAT = [
    (13, 3),
    (22, 5),
    (44, 3),
    (54, 1),
]
EXTRA_BEATS = 2

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def pitch_name(note_number):
    octave = (note_number // 12) - 1
    return f"{NOTE_NAMES[note_number % 12]}{octave}"


def find_time_signature(mid):
    """Return (numerator, denominator) from the first time-signature meta event, defaulting to 4/4."""
    for track in mid.tracks:
        for msg in track:
            if msg.is_meta and msg.type == "time_signature":
                return msg.numerator, msg.denominator
    return 4, 4


def ticks_to_measure_beat(abs_tick, ticks_per_beat, numerator, denominator):
    """Return (measure, beat) where measure starts at 1 and beat is a float starting at 1.0.

    Beat unit follows the time signature: denominator=4 means quarter-note beat,
    denominator=8 means eighth-note beat, etc.
    """
    ticks_per_unit = ticks_per_beat * 4 / denominator
    units = abs_tick / ticks_per_unit
    measure = int(units // numerator) + 1
    beat = (units % numerator) + 1
    return measure, beat


def extract_notes(track, ticks_per_beat, numerator, denominator):
    """Walk a track and return list of dicts: one row per completed note (note_on matched to note_off)."""
    abs_tick = 0
    open_notes = {}  # (channel, pitch) -> list of (start_tick, velocity)
    notes = []
    for msg in track:
        abs_tick += msg.time
        if msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
            open_notes.setdefault((msg.channel, msg.note), []).append((abs_tick, msg.velocity))
        elif msg.type == "note_off" or (msg.type == "note_on" and getattr(msg, "velocity", 0) == 0):
            stack = open_notes.get((msg.channel, msg.note))
            if stack:
                start_tick, velocity = stack.pop(0)
                measure, beat = ticks_to_measure_beat(start_tick, ticks_per_beat, numerator, denominator)
                notes.append({
                    "measure": measure,
                    "beat": round(beat, 3),
                    "pitch": pitch_name(msg.note),
                    "midi": msg.note,
                    "duration_beats": round((abs_tick - start_tick) / ticks_per_beat, 3),
                    "velocity": velocity,
                    "channel": msg.channel,
                    "start_tick": start_tick,
                })
    return notes


streamlit.header("Watermelon Crawl — MIDI Modification")

mid = mido.MidiFile(INPUT_PATH)
numerator, denominator = find_time_signature(mid)

streamlit.subheader("Source file")
streamlit.write(f"Path: `{INPUT_PATH}`")
streamlit.write(
    f"Type: {mid.type}  Tracks: {len(mid.tracks)}  Length: {mid.length:.2f}s  "
    f"Ticks/beat: {mid.ticks_per_beat}  Time signature: {numerator}/{denominator}"
)

streamlit.subheader("Track inspector")

track_summaries = []
all_notes_by_track = {}
for i, track in enumerate(mid.tracks):
    notes = extract_notes(track, mid.ticks_per_beat, numerator, denominator)
    all_notes_by_track[i] = notes
    if notes:
        pitches = [n["midi"] for n in notes]
        track_summaries.append({
            "track": i,
            "name": track.name or "(unnamed)",
            "notes": len(notes),
            "low": pitch_name(min(pitches)),
            "high": pitch_name(max(pitches)),
            "first_measure": notes[0]["measure"],
            "last_measure": notes[-1]["measure"],
        })
    else:
        track_summaries.append({
            "track": i,
            "name": track.name or "(unnamed)",
            "notes": 0,
            "low": "",
            "high": "",
            "first_measure": "",
            "last_measure": "",
        })

streamlit.dataframe(pandas.DataFrame(track_summaries), hide_index=True)

note_tracks = [s["track"] for s in track_summaries if s["notes"] > 0]
if note_tracks:
    selected = streamlit.selectbox(
        "Inspect notes in track",
        note_tracks,
        format_func=lambda i: f"{i}: {track_summaries[i]['name']} ({track_summaries[i]['notes']} notes)",
    )
    notes_df = pandas.DataFrame(all_notes_by_track[selected])
    max_measure = int(notes_df["measure"].max()) if not notes_df.empty else 1
    m_lo, m_hi = streamlit.slider(
        "Measure range",
        min_value=1,
        max_value=max(1, max_measure),
        value=(1, min(16, max_measure)),
    )
    filtered = notes_df[(notes_df["measure"] >= m_lo) & (notes_df["measure"] <= m_hi)]
    streamlit.dataframe(filtered, hide_index=True)


def bar_beat_to_tick(bar, beat, numerator, ticks_per_beat):
    """Convert (bar, beat) in GarageBand convention (1-indexed) to absolute ticks."""
    total_beats = (bar - 1) * numerator + (beat - 1)
    return total_beats * ticks_per_beat


def insert_holds(mid: mido.MidiFile, insertion_ticks, extra_ticks) -> mido.MidiFile:
    """Return a new MidiFile with `extra_ticks` of delay inserted at each absolute tick in
    `insertion_ticks`. Held notes are extended automatically because their note_off events
    (which fall after each insertion point) get pushed later along with everything else.
    """
    out = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat, type=mid.type)
    sorted_points = sorted(insertion_ticks)
    for track in mid.tracks:
        new_track = mido.MidiTrack()
        abs_tick = 0
        remaining = list(sorted_points)
        for msg in track:
            event_abs = abs_tick + msg.time
            added = 0
            while remaining and remaining[0] <= event_abs:
                added += extra_ticks
                remaining.pop(0)
            new_msg = msg.copy(time=msg.time + added)
            new_track.append(new_msg)
            abs_tick = event_abs
        out.tracks.append(new_track)
    return out


def modify(mid: mido.MidiFile) -> mido.MidiFile:
    insertion_ticks = [
        bar_beat_to_tick(bar, beat, numerator, mid.ticks_per_beat)
        for bar, beat in INSERTION_POINTS_BAR_BEAT
    ]
    return insert_holds(mid, insertion_ticks, EXTRA_BEATS * mid.ticks_per_beat)


modified = modify(mid)

streamlit.subheader("Modifications")
streamlit.write(f"Inserting {EXTRA_BEATS} beats of hold at:")
streamlit.dataframe(
    pandas.DataFrame([
        {
            "bar.beat": f"{bar}.{beat}",
            "abs_tick": bar_beat_to_tick(bar, beat, numerator, mid.ticks_per_beat),
        }
        for bar, beat in INSERTION_POINTS_BAR_BEAT
    ]),
    hide_index=True,
)
streamlit.write(f"Original length: {mid.length:.2f}s → Modified length: {modified.length:.2f}s")

streamlit.subheader("Output")
output_path = streamlit.text_input("Output filename", value=OUTPUT_PATH)
if streamlit.button("Write modified MIDI"):
    modified.save(output_path)
    streamlit.success(f"Wrote {output_path}")
    with open(output_path, "rb") as f:
        streamlit.download_button(
            "Download modified MIDI",
            data=f.read(),
            file_name=output_path,
            mime="audio/midi",
        )
