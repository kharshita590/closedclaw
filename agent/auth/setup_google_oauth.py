from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth.oauth import run_local_oauth
from auth.scopes import CALENDAR_SCOPES, GMAIL_SCOPES


def main() -> None:
    print("Starting Gmail OAuth flow...")
    run_local_oauth("gmail_token", GMAIL_SCOPES)
    print("Saved encrypted Gmail token.")

    print("Starting Google Calendar OAuth flow...")
    run_local_oauth("calendar_token", CALENDAR_SCOPES)
    print("Saved encrypted Google Calendar token.")


if __name__ == "__main__":
    main()
