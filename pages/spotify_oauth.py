import os
import base64
import requests
import streamlit as st
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session

from spotify_streamlit_util import greet_user

# Load client secret from environment file
if os.path.exists(".environ.sh"):
    with open(".environ.sh") as IN:
        for line in IN:
            if "SPOTIFY_SECRET" in line:
                client_secret = line.split("=")[1].strip()
                break
else:
    st.write("No .environ.sh file found")

client_id = '324a778e0a6844579705bb0cb6e1493d'
AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
# REDIRECT_URI = 'https://open.spotify.com/collection/playlists'
# REDIRECT_URI = 'https://localhost:8501'
REDIRECT_URI = 'http://zielund.com/'


# Step 1: Get authorization code
auth_response = requests.get(AUTH_URL, {
    'client_id': client_id,
    'response_type': 'code',
    'redirect_uri': REDIRECT_URI,
    'scope': 'streaming user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-modify-private',
})
st.write("Auth response URL:")
st.write(auth_response.url)

# Manually extract the authorization code from the URL
auth_code = st.text_input("Enter the authorization code from the URL:")

# Step 2: Exchange authorization code for access token
auth_header = base64.urlsafe_b64encode((client_id + ':' + client_secret).encode()).decode()
headers = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'Authorization': f'Basic {auth_header}'
}

payload = {
    'grant_type': 'authorization_code',
    'code': auth_code,
    'redirect_uri': REDIRECT_URI,
    'client_id': client_id,
    'client_secret': client_secret
}

st.write("Payload:")
st.write(payload)

access_token_request = requests.post(TOKEN_URL, data=payload, headers=headers)
st.write("Access token response:")
st.write(access_token_request.text)

if access_token_request.status_code == 200:
    access_token_response_data = access_token_request.json()
    access_token = access_token_response_data['access_token']
    bearer_token = f'Bearer {access_token}'
    st.write("Access token:")
    st.write(access_token)
    with open("spotify_web_token.txt", "w") as OUT:
        OUT.write(bearer_token)
else:
    st.write("Failed to get access token")
    st.stop()

# Test it out by getting the current user's profile using plain requests
headers = {
    'Authorization': bearer_token
}
profile_response = requests.get('https://api.spotify.com/v1/me', headers=headers)
st.write("Profile response:")
st.write(profile_response.text)

greet_user(bearer_token)


