# Read data from exported favourites file
import streamlit

from local_fav_utils import favourites_url, local_favourites_file_in_project, read_local_favourites

streamlit.write("CopperKnob Favourites (download if necessary)")
streamlit.markdown(f"[{favourites_url}]({favourites_url})")

local_favourites = read_local_favourites(local_favourites_file_in_project)
streamlit.dataframe(local_favourites)
