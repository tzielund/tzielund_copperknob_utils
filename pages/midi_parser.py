# Open a midi file and parse its contents, outputting a JSON representation of the MIDI data.

import midiutil
import json
import streamlit
from midiutil import MIDIFile

streamlit.header("MIDI File Parser")
import mido

def read_midi_file(file_path):
    """Read and print basic info from a MIDI file using mido."""
    mid = mido.MidiFile(file_path)
    streamlit.write(f"MIDI file: {file_path}")
    streamlit.write(f"Type: {mid.type}")
    streamlit.write(f"Number of tracks: {len(mid.tracks)}")
    streamlit.write(f"Length (seconds): {mid.length}")
    for i, track in enumerate(mid.tracks):
        if not streamlit.checkbox(f"\nTrack {i}: {track.name}"):
            continue
        for msg in track:
            # streamlit.write(msg)
            # translate the msg to a human-readable JSON format if msg.is_meta:
            if msg.is_meta:
                msg_json = {
                    "type": msg.type,
                    "time": msg.time,
                }
                for key in msg.__dict__:
                    if key not in ["type", "time"]:
                        msg_json[key] = msg.__dict__[key]
                streamlit.json(msg_json)
            else:
                # check if it has a type, time, channel
                msg_json = {}
                if hasattr(msg, "type"):
                    msg_json["type"] = msg.type
                if hasattr(msg, "time"):
                    msg_json["time"] = msg.time
                if hasattr(msg, "channel"):
                    msg_json["channel"] = msg.channel
                # If it's a note-on and has a note, add that and the equivalent letter-octave code
                if msg.type == "note_on" and hasattr(msg, "note"):
                    msg_json["note"] = msg.note
                    # convert to letter-octave
                    note_number = msg.note
                    octave = (note_number // 12) - 1
                    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
                    # Middle C is note 60, and is C4
                    note_name = note_names[note_number % 12]
                    note_code = f"{note_name}{octave}"
                    msg_json["note_code"] = note_code
                for key in msg.__dict__:
                    if key not in ["type", "time", "channel"]:
                        msg_json[key] = msg.__dict__[key]
                streamlit.json(msg_json)



read_midi_file("Watermelon-Crawl.mid")

#
# midi_json = parse_midi_file(midi_file)
# streamlit.json(midi_json)