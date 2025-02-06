# Reads a stepsheet and converts it to a JSON structure

import streamlit
import requests
from bs4 import BeautifulSoup

import stepsheet_cache_util
from google_sheet_util import read_google_sheet

# Read the google sheet with compiled favourites
df = read_google_sheet()

# Choose a dance to parse
dance_name = streamlit.selectbox("Choose a dance to parse", df[0])

dance_url = df[df[0] == dance_name][7].values[0]

stepsheet_page_data = stepsheet_cache_util.get_cached_stepsheet(dance_url)
# Try parsing without BeautifulSoup
lines = stepsheet_page_data.text.split("\n")
sheet_content = []
in_sheetcontent = False
for line in lines:
    if line.strip() == '<div class="sheetcontent">':
        in_sheetcontent = True
    if in_sheetcontent and line.strip().startswith("<b>Last Update:"):
        in_sheetcontent = False
    if in_sheetcontent:
        sheet_content.append(line)

streamlit.write(sheet_content)



wolf_soup = BeautifulSoup(wolf_data.text, 'html.parser')

# streamlit.write(wolf_soup)

# find <div class="sheetcontent"> and extract the text
sheetcontent = wolf_soup.find("div", {"class": "sheetcontent"})

# keep the span tags as they are
sheetcontent_text = sheetcontent.text
# locate all the step spans and desc spans
sheetcontent_steps = sheetcontent.findChildren("span", {"class": "step"}, recursive=False)
sheetcontent_descs = sheetcontent.findChildren("span", {"class": "desc"}, recursive=False)
# these should be parallel arrays; make them into a dictionary
