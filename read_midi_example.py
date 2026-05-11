import mido

def read_midi_file(file_path):
    """Read and print basic info from a MIDI file using mido."""
    mid = mido.MidiFile(file_path)
    print(f"MIDI file: {file_path}")
    print(f"Type: {mid.type}")
    print(f"Number of tracks: {len(mid.tracks)}")
    print(f"Length (seconds): {mid.length}")
    for i, track in enumerate(mid.tracks):
        print(f"\nTrack {i}: {track.name}")
        for msg in track:
            print(msg)
            # Only print the first 10 messages per track for brevity
            if track.index(msg) > 10:
                print("... (truncated)")
                break

read_midi_file("Watermelon-Crawl.mid")

