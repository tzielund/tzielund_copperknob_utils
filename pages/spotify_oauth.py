import os
import base64
import requests
import streamlit as st
from urllib.parse import urlencode

from spotify_streamlit_util import greet_user

CLIENT_ID = '324a778e0a6844579705bb0cb6e1493d'
REDIRECT_URI = 'https://127.0.0.1:8501/spotify_oauth'
AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
SCOPES = (
    'streaming user-read-playback-state user-modify-playback-state '
    'user-read-currently-playing playlist-modify-private playlist-modify-public'
)

st.title("Spotify Authorization")


def load_client_secret():
    if os.path.exists(".environ.sh"):
        with open(".environ.sh") as f:
            for line in f:
                if "SPOTIFY_SECRET" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


client_secret = load_client_secret()
if not client_secret:
    st.error("Could not find SPOTIFY_SECRET in .environ.sh")
    st.stop()

code = st.query_params.get("code")
error = st.query_params.get("error")

if error:
    st.error(f"Spotify authorization denied: {error}")
    st.query_params.clear()

elif code:
    with st.spinner("Exchanging code for token…"):
        auth_header = base64.urlsafe_b64encode(
            f"{CLIENT_ID}:{client_secret}".encode()
        ).decode()
        response = requests.post(
            TOKEN_URL,
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': REDIRECT_URI,
                'client_id': CLIENT_ID,
                'client_secret': client_secret,
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Authorization': f'Basic {auth_header}',
            },
        )

    if response.status_code == 200:
        bearer_token = f"Bearer {response.json()['access_token']}"
        with open("spotify_web_token.txt", "w") as f:
            f.write(bearer_token)
        st.query_params.clear()
        st.success("Spotify connected! Token saved.")
        greet_user(bearer_token)
    else:
        st.error(f"Token exchange failed: {response.text}")

else:
    auth_link = AUTH_URL + '?' + urlencode({
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
    })
    st.markdown(
        f"[Click here to authorize with Spotify ↗]({auth_link})",
    )
    st.info(
        "After clicking, Spotify will ask you to log in and approve access. "
        "You'll be redirected back here automatically and the token will be saved."
    )
    st.caption(
        "Note: your browser will warn about a self-signed certificate. "
        "Accept it to continue — this is expected for local development."
    )
