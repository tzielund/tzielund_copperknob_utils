import pandas

favourites_url = "https://www.copperknob.co.uk/lists/47673/favourites"
local_favourites_file_in_project = "favourites.csv"


def read_local_favourites(filename):
    with open(filename) as IN:
        # read the file into a dataframe
        df = pandas.read_csv(IN)
        return df
