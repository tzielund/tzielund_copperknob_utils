import os

import gspread
import pandas

spreadsheet_url = "https://docs.google.com/spreadsheets/d/1ZoPjRSl1K43XZY77ThkV-qZwzzMWYl3HY__4KhnZuYs/edit?usp=sharing"
google_api_key = os.environ["GOOGLE_API_KEY"]


def read_google_sheet():
    gc = gspread.api_key(google_api_key)
    sh = gc.open_by_url(spreadsheet_url)
    worksheet = sh.get_worksheet(0)
    data = worksheet.get_all_values()
    df = pandas.DataFrame(data)
    return df
