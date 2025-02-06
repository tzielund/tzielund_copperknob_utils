import streamlit

# Scrape the data from the CopperKnob website
import requests
from bs4 import BeautifulSoup
import pandas

page = requests.get("https://www.copperknob.co.uk/")
soup = BeautifulSoup(page.content, "html.parser")

streamlit.write("CopperKnob Dance Steps")
streamlit.write(soup)
table = soup.find("table", {"class": "table table-striped table-hover table-condensed"})
rows = table.find_all("tr")
data = []
for row in rows:
    cols = row.find_all("td")
    cols = [ele.text.strip() for ele in cols]
    data.append([ele for ele in cols if ele])

df = pandas.DataFrame(data)
streamlit.dataframe(df)