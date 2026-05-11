# Scan the Copperknob top 100 step sheet list and cache each of the step sheets
import datetime

import streamlit
import os
import requests
import json
from bs4 import BeautifulSoup

from stepsheet_util import Stepsheet

COPPERKNOB_RECENT_100_URL = "https://www.copperknob.co.uk/recentlyadded?Filter=1"
COPPERKNOB_TOP_100_URL = "https://www.copperknob.co.uk/mostpopular"
# iterate adding &recnum=20,40,60,and 80 to get more results adding up to 100

def get_top_n_list(start_from=0, max_results=100):
    print(f"Fetching top {max_results} list starting from {start_from}")
    specific_url = COPPERKNOB_TOP_100_URL + f"?recnum={start_from}"
    if start_from == 0:
        specific_url = COPPERKNOB_TOP_100_URL
    print(f"Fetching URL: {specific_url}")
    response = requests.get(specific_url)
    if response.status_code != 200:
        print(f"Error fetching top 100 list: {response.status_code}")
        print(response.text)
        raise Exception(f"Error fetching top 100 list: {response.status_code}")
    # the response is HTML, we need to parse it to extract the step sheet URLs
    # there's a sequence of lines like this:
    # <div class="listitem" onClick="location.href='https://www.copperknob.co.uk/stepsheets/203500/giddy-up-get-down';">
    # but let's use BeautifulSoup to parse it properly
    step_sheet_urls = list()
    soup = BeautifulSoup(response.text, 'html.parser')
    list_items = soup.find_all('div', class_='listitem')
    for item in list_items:
        on_click = item.get('onclick', '')
        if "location.href='" in on_click:
            url_part = on_click.split("location.href='")[1].split("';")[0]
            step_sheet_urls.append(url_part)
    print(f"Found {len(step_sheet_urls)} step sheet URLs on this page.")
    # # if we have more than max_results, trim the list (this shouldn't happen in practice)
    # if len(step_sheet_urls) > max_results:
    #     print(f"Trimming step sheet URLs from {len(step_sheet_urls)} to {max_results}")
    #     step_sheet_urls = step_sheet_urls[:max_results]
    # if we have less than max_results, we may need to fetch more pages
    if len(step_sheet_urls) < max_results and start_from + 20 < 100:
        print("Recursing to fetch more step sheets...")
        step_sheet_urls.extend(get_top_n_list(start_from + 20, max_results - len(step_sheet_urls)))
    if start_from == 0:
        print(f"Final length of step sheet URLs: {len(step_sheet_urls)}")
    return step_sheet_urls

def scan_top_100_stepsheets():
    streamlit.title("Copperknob Top 100 Step Sheet Scanner")
    streamlit.write("Scanning the Copperknob Top 100 step sheets and caching them locally.")
    step_sheet_urls = get_top_n_list()
    streamlit.write(f"Found {len(step_sheet_urls)} step sheets.")
    # Create a directory to store cached step sheets
    cache_dir = "stepsheet_cache"
    os.makedirs(cache_dir, exist_ok=True)
    topn_dir = "stepsheet_topn_cache"
    os.makedirs(topn_dir, exist_ok=True)
    # Open a jsonl file to log the step sheet metadata
    todays_date_stamp = datetime.datetime.now().strftime("%Y-%m-%d")
    log_filename = os.path.join(topn_dir, f"top_100_stepsheet_{todays_date_stamp}.jsonl")
    with open(log_filename, "w") as LOG:
        rank = 1
        for dance_url in step_sheet_urls:
            streamlit.write(f"Processing: {dance_url}")
            sheet = Stepsheet(dance_url)
            streamlit.write(f"Cached step sheet {sheet.name} metadata.")
            metadata = sheet.parse_metadata()
            # Write metadata to log file
            log_record = metadata.copy()
            log_record["rank"] = rank
            log_record["url"] = dance_url
            LOG.write(json.dumps(log_record) + "\n")
            rank += 1



result= get_top_n_list()
streamlit.json(result)
scan_top_100_stepsheets()