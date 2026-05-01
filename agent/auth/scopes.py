GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

ALL_GOOGLE_SCOPES = sorted(set(GMAIL_SCOPES + CALENDAR_SCOPES))
