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
    (74, 1),
    (83, 1),
]
EXTRA_BEATS = 2

# Rhythm-section tracks. During each inserted hold, the prior 2 beats of notes from
# these tracks are duplicated into the gap so the rhythm continues instead of going silent.
RHYTHM_TRACK_INDICES = [3, 9, 10, 11]

# Bar ranges to remove (1-indexed, inclusive on both ends) in the ORIGINAL timeline.
# Events inside the range are dropped; events after are shifted earlier to close the gap.
REMOVE_BAR_RANGES = [(35, 36)]

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


def remove_bar_range(mid: mido.MidiFile, bar_start, bar_end_inclusive, numerator) -> mido.MidiFile:
    """Excise bars [bar_start, bar_end_inclusive] (1-indexed) from each track.

    Events inside the range are dropped. Events after the range shift earlier by the deleted span.
    For notes that start before the range and end inside it, the note_off is truncated to the
    start of the deletion. Notes whose note_on falls inside the range are dropped entirely.
    """
    tpb = mid.ticks_per_beat
    T_start = (bar_start - 1) * numerator * tpb
    T_end = bar_end_inclusive * numerator * tpb
    span = T_end - T_start

    out = mido.MidiFile(ticks_per_beat=tpb, type=mid.type)
    for track in mid.tracks:
        orig_events = []
        abs_t = 0
        for msg in track:
            abs_t += msg.time
            orig_events.append((abs_t, msg))

        # Pair note_ons with their note_offs
        open_notes = {}
        on_to_off_idx = {}
        for idx, (at, msg) in enumerate(orig_events):
            if msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
                open_notes.setdefault((msg.channel, msg.note), []).append(idx)
            elif msg.type == "note_off" or (msg.type == "note_on" and getattr(msg, "velocity", 0) == 0):
                stack = open_notes.get((msg.channel, msg.note))
                if stack:
                    on_to_off_idx[stack.pop(0)] = idx

        drop = set(idx for idx, (at, _) in enumerate(orig_events) if T_start <= at < T_end)
        truncate_to = {}  # idx -> new abs time

        for on_idx, off_idx in on_to_off_idx.items():
            on_t = orig_events[on_idx][0]
            off_t = orig_events[off_idx][0]
            if T_start <= on_t < T_end:
                drop.add(on_idx)
                drop.add(off_idx)
            elif on_t < T_start and T_start <= off_t < T_end:
                drop.discard(off_idx)
                truncate_to[off_idx] = T_start

        new_events = []
        for idx, (at, msg) in enumerate(orig_events):
            if idx in drop:
                continue
            new_t = truncate_to.get(idx, at)
            if new_t >= T_end:
                new_t -= span
            new_events.append((new_t, msg))

        new_events.sort(key=lambda e: e[0])
        new_track = mido.MidiTrack()
        prev = 0
        for at, msg in new_events:
            new_track.append(msg.copy(time=at - prev))
            prev = at
        out.tracks.append(new_track)
    return out


def _collect_source_window_notes(orig_events, window_start, window_end):
    """Return list of (note_on_abs, note_on_msg, note_off_abs, note_off_msg) for notes whose
    note_on AND matching note_off both fall inside [window_start, window_end).
    """
    open_notes = {}
    pairs = []
    for abs_t, msg in orig_events:
        if msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
            open_notes.setdefault((msg.channel, msg.note), []).append((abs_t, msg))
        elif msg.type == "note_off" or (msg.type == "note_on" and getattr(msg, "velocity", 0) == 0):
            stack = open_notes.get((msg.channel, msg.note))
            if stack:
                on_abs, on_msg = stack.pop(0)
                if window_start <= on_abs < window_end and window_start <= abs_t < window_end:
                    pairs.append((on_abs, on_msg, abs_t, msg))
    return pairs


def insert_holds(mid: mido.MidiFile, insertion_ticks, extra_ticks, rhythm_track_indices=()) -> mido.MidiFile:
    """Return a new MidiFile with `extra_ticks` of delay inserted at each absolute tick in
    `insertion_ticks`. Held notes are extended automatically because their note_off events
    (which fall after each insertion point) get pushed later along with everything else.

    For tracks in `rhythm_track_indices`, the notes in [T - extra_ticks, T) are also copied
    into the inserted gap so the rhythm continues across the hold instead of going silent.
    """
    out = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat, type=mid.type)
    sorted_points = sorted(insertion_ticks)
    rhythm_set = set(rhythm_track_indices)

    for track_idx, track in enumerate(mid.tracks):
        # Decode to (abs_tick, msg) tuples
        orig_events = []
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            orig_events.append((abs_tick, msg))

        # Shift every event by (number of insertion points at or before its time) * extra_ticks
        new_events = []
        for abs_t, msg in orig_events:
            shift = extra_ticks * sum(1 for p in sorted_points if p <= abs_t)
            new_events.append((abs_t + shift, msg))

        # For rhythm tracks, also inject copies of the prior 2 beats into each gap.
        # Gap for insertion i (0-indexed) occupies output ticks [T_i + i*extra, T_i + (i+1)*extra),
        # so each copied event at original time t goes to output time t + (i+1)*extra.
        if track_idx in rhythm_set:
            for i, T_i in enumerate(sorted_points):
                pairs = _collect_source_window_notes(orig_events, T_i - extra_ticks, T_i)
                copy_offset = (i + 1) * extra_ticks
                for on_abs, on_msg, off_abs, off_msg in pairs:
                    new_events.append((on_abs + copy_offset, on_msg))
                    new_events.append((off_abs + copy_offset, off_msg))

        # Sort: stable by absolute time so original event order is preserved at ties.
        new_events.sort(key=lambda e: e[0])

        # Re-encode as delta times
        new_track = mido.MidiTrack()
        prev = 0
        for abs_t, msg in new_events:
            new_track.append(msg.copy(time=abs_t - prev))
            prev = abs_t
        out.tracks.append(new_track)
    return out


def modify(mid: mido.MidiFile) -> mido.MidiFile:
    tpb = mid.ticks_per_beat
    insertion_ticks = [
        bar_beat_to_tick(bar, beat, numerator, tpb)
        for bar, beat in INSERTION_POINTS_BAR_BEAT
    ]

    # Apply each removal in reverse order so earlier-bar offsets in REMOVE_BAR_RANGES don't
    # invalidate later ones. Insertion points after a removal get shifted earlier by the
    # removed span so they still land at the right musical moment in the shortened timeline.
    working = mid
    for bar_start, bar_end_inclusive in sorted(REMOVE_BAR_RANGES, reverse=True):
        working = remove_bar_range(working, bar_start, bar_end_inclusive, numerator)
        T_start = (bar_start - 1) * numerator * tpb
        T_end = bar_end_inclusive * numerator * tpb
        span = T_end - T_start
        insertion_ticks = [t - span if t >= T_end else t for t in insertion_ticks]

    return insert_holds(
        working,
        insertion_ticks,
        EXTRA_BEATS * tpb,
        rhythm_track_indices=RHYTHM_TRACK_INDICES,
    )


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
rhythm_names = [f"{i} ({track_summaries[i]['name']})" for i in RHYTHM_TRACK_INDICES if i < len(track_summaries)]
streamlit.write("Rhythm tracks copied into each gap: " + ", ".join(rhythm_names))
if REMOVE_BAR_RANGES:
    streamlit.write("Removing bar ranges (original numbering, inclusive): " +
                    ", ".join(f"{a}-{b}" for a, b in REMOVE_BAR_RANGES))
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
