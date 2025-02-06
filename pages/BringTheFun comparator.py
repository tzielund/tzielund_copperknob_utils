import json

# Compare data from BringTheFun to the Google Sheet

import streamlit
import google_sheet_util
import os

streamlit.header("BringTheFun comparator")

cache_file = "BringTheFun_cache.json"
if os.path.exists(cache_file):
    with open(cache_file, "r") as f:
        cache = json.load(f)
        dance_list = cache["dance_list"]
        practice_list = cache["practice_list"]
        learn_list = cache["learn_list"]
    streamlit.write("Loaded cache")
    replace_cache_button = streamlit.checkbox("Replace cache")
else:
    replace_cache_button = True
    dance_list = ""
    practice_list = ""
    learn_list = ""
    cache = dict()
    cache["dance_list"] = dance_list
    cache["practice_list"] = practice_list
    cache["learn_list"] = learn_list

if replace_cache_button:
    streamlit.markdown(f"Open the [BringTheFun list](https://bringthefun.dance/my-dances) and copy/paste the data here. Then click the 'Compare' button to compare the data below")
    BTF_dance_list = streamlit.text_area("Main dance list (paste here)", value=dance_list)
    BTF_practice_list = streamlit.text_area("Practice dance list (paste here)", value=practice_list)
    BTF_learn_list = streamlit.text_area("Learn dance list (paste here)", value=learn_list)
    use_these_values = streamlit.button("Use these values")
    if use_these_values:
        cache["dance_list"] = BTF_dance_list
        cache["practice_list"] = BTF_practice_list
        cache["learn_list"] = BTF_learn_list
        with open(cache_file, "w") as f:
            json.dump(cache, f)
        streamlit.rerun()
    else:
        streamlit.stop()

def parse_dance_list(lines):
    # Parse the data to identify specific dances
    # Pattern for a dance is three lines:
    # 1. Dance name
    # 2. rating
    # 3. choreographer
    # Then a blank line
    dances = []
    for i in range(1, len(lines)):
        if lines[i] == "":
            if lines[i-1].startswith("Choreo"):
            # if True:
                dances.append({
                    "name": lines[i-3],
                    "rating": lines[i-2],
                    "choreographer": lines[i-1]
                })
    return dances

dances = parse_dance_list(dance_list.split("\n"))
practice_dances = parse_dance_list(practice_list.split("\n"))
learn_dances = parse_dance_list(learn_list.split("\n"))
all_dances = dances + practice_dances + learn_dances

show_parsed_data = streamlit.checkbox("Show parsed data")
if show_parsed_data:
    streamlit.write(all_dances)

google_sheet = google_sheet_util.read_google_sheet()
show_google_sheet = streamlit.checkbox("Show Google Sheet data")
if show_google_sheet:
    streamlit.write(google_sheet)
# streamlit.write(google_sheet)

def normalize_name(name):
    name_norm = name.lower().replace(" ", "")
    name_norm = name_norm.replace('"', "")
    name_norm = name_norm.replace("'", "")
    name_norm = name_norm.replace("‘", "")
    return name_norm

# Compare the data
dance_index = dict()
for row in all_dances:
    dance_name = row["name"]
    dance_name_norm = normalize_name(dance_name)
    dance_index[dance_name_norm] = row

# Two column comparison.
# Left column is where BTF data is unmatched
# Rite column is where Google Sheet data is unmatched

streamlit.header("Comparison")
left_col, rite_col = streamlit.columns(2)
left_col.header("BTF unmatched")
rite_col.header("Google Sheet unmatched")
for index, row in google_sheet.iterrows():
    google_sheet_name = row[0]
    google_sheet_name_norm = normalize_name(google_sheet_name)
    found = False
    if google_sheet_name_norm in dance_index:
        found = True
        # streamlit.write(f"Match: {google_sheet_name}")
    if not found:
        google_sheet_url = row[7]
        left_col.markdown(f"No match: [{google_sheet_name}]({google_sheet_url})")

for dance_name_norm in dance_index:
    row = dance_index[dance_name_norm]
    dance_name = row["name"]
    dance_name_norm = normalize_name(dance_name)
    found = False
    for index, row in google_sheet.iterrows():
        google_sheet_name = row[0]
        google_sheet_name_norm = normalize_name(google_sheet_name)
        if google_sheet_name_norm == dance_name_norm:
            found = True
            # streamlit.write(f"Match: {google_sheet_name}")
    if not found:
        rite_col.markdown(f"No match: {dance_name}")