# Scan email messages using jmap looking for line dance related newsletters

import os
import time
import json
import streamlit
import requests
from tiny_jmap_library import TinyJMAPClient


# Settings
JMAP_USER = "tzielund@fastmail.fm"
JMAP_SERVER = "api.fastmail.com"

with open (".environ.sh", 'r') as IN:
    lines = IN.readlines()
    for line in lines:
        line = line.strip()
        if line.startswith("export SPOTIFY_SECRET="):
            JMAP_TOKEN = line.split("=")[1]
            break
    else:
        raise ValueError("JMAP_TOKEN not found in .environ.sh")

client = TinyJMAPClient(JMAP_SERVER, JMAP_USER, JMAP_TOKEN)
account_id = client.get_account_id()

inbox_res = client.make_jmap_call(
    {
        "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        "methodCalls": [
            [
                "Mailbox/query",
                {
                    "accountId": account_id,
                    "filter": {"role": "inbox", "hasAnyRole": True},
                },
                "a",
            ]
        ],
    }
)
inbox_id = inbox_res["methodResponses"][0][1]["ids"][0]
assert len(inbox_id) > 0

