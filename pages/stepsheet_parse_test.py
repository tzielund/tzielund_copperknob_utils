# Tests some of the stepsheet parse functions with examples from Copperknob

import streamlit
from stepsheet_util import Stepsheet

test1_url = "https://www.copperknob.co.uk/stepsheets/203105/shine-like-me"

streamlit.write("Stepsheet Parse Test")
stepsheet1 = Stepsheet(test1_url)
streamlit.write(stepsheet1)

streamlit.write("Got it")
content = stepsheet1.page_data
# if stepsheet1.__check_cloudflare_block(content):
#     streamlit.write("Cloudflare block detected!")
streamlit.write("Raw sheet content:")
streamlit.text_area("Sheet Content", content, height=300)
stepsheet1.parse()

streamlit.write(stepsheet1.metadata)