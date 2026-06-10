"""Convert between MIDI and ABC notation. Uses the abcmidi tool suite.

Prereqs:
    brew install abcmidi
"""

import os
import subprocess
import tempfile

import streamlit as st

ABC_OUTPUT_DIR = "abc_output/"
DEFAULT_MIDI_PATH = "Watermelon-Crawl.mid"
SAMPLE_ABC = """X:1
T:Hello World
M:4/4
L:1/4
K:C
|: C D E F | G A B c :|
"""

st.set_page_config(page_title="ABC Notation", layout="wide")
st.title("ABC Notation")


def have(cmd):
    try:
        subprocess.run([cmd, "-h"], capture_output=True, timeout=2)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


if not (have("midi2abc") and have("abc2midi")):
    st.error("abcmidi tools not found on PATH. Install with: `brew install abcmidi`")
    st.stop()


tab_to_abc, tab_to_midi = st.tabs(["MIDI → ABC", "ABC → MIDI"])

with tab_to_abc:
    source = st.radio(
        "Source",
        ["Local path", "Upload"],
        horizontal=True,
        index=0,
        key="midi_src",
    )
    midi_bytes = None
    midi_name = "input.mid"
    if source == "Local path":
        path = st.text_input("MIDI file path", value=DEFAULT_MIDI_PATH)
        if path:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    midi_bytes = f.read()
                midi_name = os.path.basename(path)
            else:
                st.warning(f"File not found: {path}")
    else:
        up = st.file_uploader("MIDI file", type=["mid", "midi"])
        if up:
            midi_bytes = up.getvalue()
            midi_name = up.name

    if midi_bytes and st.button("Convert to ABC"):
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
            tmp.write(midi_bytes)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["midi2abc", tmp_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                st.error(f"midi2abc failed:\n{result.stderr}")
            else:
                st.session_state["abc_text"] = result.stdout
        finally:
            os.unlink(tmp_path)

    abc_text = st.session_state.get("abc_text", "")
    if abc_text:
        st.text_area("ABC output", abc_text, height=400, key="abc_out_view")
        st.download_button(
            "Download ABC",
            abc_text,
            file_name=os.path.splitext(midi_name)[0] + ".abc",
            mime="text/plain",
        )

with tab_to_midi:
    abc_input = st.text_area("ABC input", value=SAMPLE_ABC, height=300, key="abc_in")
    if abc_input.strip() and st.button("Convert to MIDI"):
        os.makedirs(ABC_OUTPUT_DIR, exist_ok=True)
        # Derive a sensible filename from the T: header if present
        title = "abc_output"
        for line in abc_input.splitlines():
            if line.startswith("T:"):
                title = line[2:].strip().replace(" ", "_") or "abc_output"
                break
        out_path = os.path.abspath(os.path.join(ABC_OUTPUT_DIR, f"{title}.mid"))

        with tempfile.NamedTemporaryFile(suffix=".abc", delete=False, mode="w") as tmp:
            tmp.write(abc_input)
            abc_path = tmp.name
        try:
            result = subprocess.run(
                ["abc2midi", abc_path, "-o", out_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                st.error(f"abc2midi failed:\n{result.stderr}")
            else:
                st.success(f"Wrote {out_path}")
                with open(out_path, "rb") as f:
                    midi_data = f.read()
                st.download_button(
                    "Download MIDI",
                    midi_data,
                    file_name=os.path.basename(out_path),
                    mime="audio/midi",
                )
                if result.stdout.strip():
                    with st.expander("abc2midi messages"):
                        st.code(result.stdout)
        finally:
            os.unlink(abc_path)
