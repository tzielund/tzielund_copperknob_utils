# Scan email messages using jmap looking for line dance related newsletters

import os
import time
import json
from email.header import decode_header

import streamlit
from email import message_from_binary_file

# Extract the body text from the email
def extract_body(message):
    if message.is_multipart():
        for part in message.get_payload():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8")
    else:
        return message.get_payload(decode=True).decode(message.get_content_charset() or "utf-8")
    return None

def clean_subject(subject):
    decoded_parts = decode_header(subject)
    cleaned_subject = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            cleaned_subject += part.decode(encoding or "utf-8")
        else:
            cleaned_subject += part
    return cleaned_subject

# Read files from email archive
email_archive_folder = "tzielund_fastmail_fm_2025-May-09_INBOX_Line_dance_DQWL"
email_archive_files = os.listdir(email_archive_folder)
for file in email_archive_files:
    if not file.endswith(".eml"):
        continue
    # Read the .eml file and extract the subject
    with open(f"{email_archive_folder}/{file}", 'rb') as IN:
        m = message_from_binary_file(IN)
        # Identify the from, to, subject and message body from m
        from_ = m["From"]
        to_ = m["To"]
        subject = clean_subject(m["Subject"])
        date = m["Date"]
        body = extract_body(m)
        # show it
        one_line_summary = f"{subject} ({from_})"
        show_it_checkbox = streamlit.checkbox(one_line_summary, value=False, key=file)
        if not show_it_checkbox:
            continue
        streamlit.write(f"From: {from_}")
        streamlit.write(f"To: {to_}")
        streamlit.write(f"Subject: {subject}")
        streamlit.write(f"Date: {date}")
        # Show the body of the email as a text area
        streamlit.text_area("Body", body, height=300)
        # streamlit.write(f"Body: {body}")
        # Add a horizontal line
        streamlit.markdown("---")




