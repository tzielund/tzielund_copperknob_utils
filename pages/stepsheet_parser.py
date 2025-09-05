# Reads a stepsheet and converts it to a JSON structure
import re

import streamlit
import requests
from bs4 import BeautifulSoup

import stepsheet_util
from stepsheet_util import Stepsheet
from google_sheet_util import read_google_sheet

# Read the google sheet with compiled favourites
df = read_google_sheet()

# Choose a dance to look at more closely
dance_name = streamlit.selectbox("Choose a dance to review", df[0])
dance_url = df[df[0] == dance_name][7].values[0]

# Show the copperknob URL
streamlit.write(f"Copperknob URL: {dance_url}")

stepsheet = Stepsheet(dance_url)
stepsheet.parse()

# Show the metadata
metadata = stepsheet.metadata
streamlit.write("Metadata")
streamlit.json(metadata)

show_content = streamlit.checkbox("Show stepsheet content")
if show_content:
    stepsheet_content = stepsheet.sheet_content
    content_as_a_string = stepsheet_content
    content_viewer = streamlit.text_area("Stepsheet content", content_as_a_string, disabled=True)

show_steps_checkbox = streamlit.checkbox("Show steps")
if show_steps_checkbox:
    steps = stepsheet.steps
    streamlit.write("Steps")
    streamlit.json(steps)

show_sections = streamlit.checkbox("Show sections")
if show_sections:
    sections = stepsheet.sections
    streamlit.write("Sections")
    streamlit.json(sections)


# display each section
for section in sections:
    streamlit.write("Section")
    streamlit.json(section)
