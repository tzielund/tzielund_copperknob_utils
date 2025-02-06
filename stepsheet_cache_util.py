# Utilities to read stepsheet data from a file or URL

import requests
from bs4 import BeautifulSoup
import os

stepsheet_cache_dir = "stepsheet_cache/"
stepsheet_cache_file_extension = ".html"
os.makedirs(stepsheet_cache_dir, exist_ok=True)

def get_cached_stepsheet(url):
    # Use the last two parts of the URL to create a filename
    stepsheet_id = url.split("/")[-2]
    stepsheet_name = url.split("/")[-1]
    cache_filename = os.path.join(stepsheet_cache_dir, stepsheet_id + "_" + stepsheet_name + stepsheet_cache_file_extension)
    if os.path.exists(cache_filename):
        with open(cache_filename, "r") as cache_file:
            return cache_file.read()
    else:
        stepsheet_data = requests.get(url)
        with open(cache_filename, "w") as cache_file:
            cache_file.write(stepsheet_data.text)
        return stepsheet_data.text