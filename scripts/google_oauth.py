"""One-time OAuth for each inbox. Run locally, once per account:

    python scripts/google_oauth.py

A browser opens -> pick the account (gomehsaias@gmail.com, then re-run for
gs@bacimilanousa.com and store@eienhealth.com) -> Allow. The refresh token
prints here; paste it into GMAIL_ACCOUNTS_JSON on Render. You never sign out
of anything — Google's account picker handles multiple accounts.

Requires GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in your environment or .env
(create a Desktop-type OAuth client in Google Cloud Console, with the Gmail
API enabled and the three addresses added as test users).
"""
import json
import os

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    },
    SCOPES,
)
creds = flow.run_local_server(port=0, prompt="consent")

print("\n=== SUCCESS — add this to GMAIL_ACCOUNTS_JSON ===\n")
print(json.dumps({"<alias>": {"email": "<the address you just authorized>",
                              "refresh_token": creds.refresh_token}}, indent=2))
print("\nAliases used by the agent: personal | baci | eien")
