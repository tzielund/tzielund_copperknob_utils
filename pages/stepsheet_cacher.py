# Load all the stepsheets from the google sheet and cache them

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

# Cache all the listed stepsheets
for index, row in df.iterrows():
    dance_url = row[7]
    if dance_url:
        streamlit.write(f"Caching {dance_url}")
        sheet = Stepsheet(dance_url)
        sheet.parse()
