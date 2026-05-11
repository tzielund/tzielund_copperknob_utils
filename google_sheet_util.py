import gspread
import pandas

gc = gspread.service_account(filename="book-bingo-gbapi-d6b744a8292f.json")


# # Get the API key from the environment, or from .environ.sh
# if "GOOGLE_API_KEY" not in os.environ:
#     if os.path.exists(".environ.sh"):
#         with open(".environ.sh") as IN:
#             for line in IN:
#                 line = line.strip()
#                 if line.startswith("export GOOGLE_API_KEY="):
#                     line = line[len("export GOOGLE_API_KEY="):]
#                     os.environ["GOOGLE_API_KEY"] = line
#                     break
#

spreadsheet_url = "https://docs.google.com/spreadsheets/d/1ZoPjRSl1K43XZY77ThkV-qZwzzMWYl3HY__4KhnZuYs/edit?usp=sharing"
# google_api_key = os.environ["GOOGLE_API_KEY"]


def read_google_sheet():
    sh = gc.open_by_url(spreadsheet_url)
    worksheet = sh.get_worksheet(0)
    data = worksheet.get_all_values()
    df = pandas.DataFrame(data)
    return df

def read_google_sheet_as_worksheet():
    sh = gc.open_by_url(spreadsheet_url)
    worksheet = sh.get_worksheet(0)
    return worksheet

def get_song_list_selector(sheet):
    # Return a displayable list of songs mapped to their spotify urls
    song_list = sheet[[5, 6]]
    song_list = song_list.apply(lambda x: f"{x[5]} by {x[6]}", axis=1).tolist()
    spotify_list = sheet[8].tolist()
    song_dict = dict(zip(song_list, spotify_list))
    return song_dict

def update_copperknob_url_at(df_row_index, new_url, url_column_index=7):
    """Update the URL column of a known row. df_row_index is 0-based from the DataFrame;
    gspread is 1-based for both row and column.
    """
    worksheet = read_google_sheet_as_worksheet()
    worksheet.update_cell(df_row_index + 1, url_column_index + 1, new_url)
    return f"Updated row {df_row_index + 1} -> {new_url}"


def add_dance_to_sheet(sheet, dance_name, choreographer, count, walls, level, song_name, song_artist, spotify_url):
    new_row = {
        0: dance_name,
        1: choreographer,
        2: count,
        3: walls,
        4: level,
        5: song_name,
        6: song_artist,
        7: spotify_url
    }
    worksheet = read_google_sheet_as_worksheet()
    worksheet.append_row(list(new_row.values()))
    return "Dance added to sheet."