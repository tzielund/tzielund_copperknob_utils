import os

import gspread
import pandas

# Get the API key from the environment, or from .environ.sh
if "GOOGLE_API_KEY" not in os.environ:
    if os.path.exists(".environ.sh"):
        with open(".environ.sh") as IN:
            for line in IN:
                line = line.strip()
                if line.startswith("export GOOGLE_API_KEY="):
                    line = line[len("export GOOGLE_API_KEY="):]
                    os.environ["GOOGLE_API_KEY"] = line
                    break


spreadsheet_url = "https://docs.google.com/spreadsheets/d/1ZoPjRSl1K43XZY77ThkV-qZwzzMWYl3HY__4KhnZuYs/edit?usp=sharing"
google_api_key = os.environ["GOOGLE_API_KEY"]


def read_google_sheet():
    gc = gspread.api_key(google_api_key)
    sh = gc.open_by_url(spreadsheet_url)
    worksheet = sh.get_worksheet(0)
    data = worksheet.get_all_values()
    df = pandas.DataFrame(data)
    return df


def write_google_sheet(df):
    gc = gspread.api_key(google_api_key)
    sh = gc.open_by_url(spreadsheet_url)
    worksheet = sh.get_worksheet(0)
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())

def get_song_list_selector(sheet):
    # Return a displayable list of songs mapped to their spotify urls
    song_list = sheet[[5, 6]]
    song_list = song_list.apply(lambda x: f"{x[5]} by {x[6]}", axis=1).tolist()
    spotify_list = sheet[8].tolist()
    song_dict = dict(zip(song_list, spotify_list))
    return song_dict

