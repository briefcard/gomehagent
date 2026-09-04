"""SUPERSEDED — use the console's Connections tab instead.

Connect a Google account at /admin/ui?tab=accounts, with the Connect button
beside Google. That flow does everything this script does and three things it
cannot:

  * it stores the token per ACCOUNT, encrypted at rest, instead of in a
    GMAIL_ACCOUNTS_JSON env var that has to be pasted into Render by hand;
  * it records the scopes Google ACTUALLY granted, which is what
    `credentials.CAPABILITY_SCOPES` reads — a token pasted from here carries
    no scope record at all, which is why `ENV_GRANTS["google"]` grants `inbox`
    alone and Search Console reads as unwired even when it works;
  * changing it is a button, not a redeploy.

This file is kept because accounts connected before the OAuth flow existed
still resolve through GMAIL_ACCOUNTS_JSON, and because it is the only path
that works with no running service. Note its CLIENT_CONFIG uses the
`"installed"` (Desktop) shape while `oauth.FLOWS["google"]` is a hosted web
flow — one client id cannot be both, and that mismatch is a
`redirect_uri_mismatch` waiting to happen if the same credentials serve both.

Original docstring follows.
"""
"""Authorize all three inboxes and build GMAIL_ACCOUNTS_JSON automatically.

Run once:  python scripts/google_oauth.py
It walks you through all three accounts (a browser opens for each — just pick
the right account and click Allow). At the end it prints the exact
GMAIL_ACCOUNTS_JSON value to paste into Render. Tokens are also saved to
accounts.json locally (git-ignored) in case you need them again.

Requires GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env or environment.
"""
import json
import os
import pathlib

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

# Everything the agent will EVER need from Google — authorize once, never again.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",   # read/label/mark email
    "https://www.googleapis.com/auth/gmail.send",     # send approved replies
    "https://www.googleapis.com/auth/drive",          # read + organize files (Phase 3 doc filing); also covers Sheets
    "https://www.googleapis.com/auth/calendar",       # scheduling, shipment ETAs as events
    "https://www.googleapis.com/auth/webmasters.readonly",  # SEO agent: Search Console (real rankings/clicks)
    "https://www.googleapis.com/auth/analytics.readonly",   # SEO agent: GA4 (real traffic/conversions)
    "https://www.googleapis.com/auth/business.manage",      # Business Profile: listing, reviews, posts, performance (app/gbp.py)
]

ACCOUNTS = [
    ("personal", "gomehsaias@gmail.com"),
    ("baci", "gs@bacimilanousa.com"),
    ("eien", "store@eienhealth.com"),
]

CLIENT_CONFIG = {
    "installed": {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

out_path = pathlib.Path("accounts.json")
result = json.loads(out_path.read_text()) if out_path.exists() else {}

for alias, email in ACCOUNTS:
    if alias in result:
        print(f"[{alias}] {email} — already authorized, skipping.")
        continue
    input(f"\n[{alias}] Press Enter to authorize {email} "
          f"(a browser will open — PICK THIS ACCOUNT, then click Allow)...")
    flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    result[alias] = {"email": email, "refresh_token": creds.refresh_token}
    out_path.write_text(json.dumps(result, indent=2))
    print(f"[{alias}] ✅ authorized.")

print("\n" + "=" * 60)
print("DONE. Paste this as the GMAIL_ACCOUNTS_JSON env var in Render:")
print("=" * 60 + "\n")
print(json.dumps(result, separators=(",", ":")))
print("\n(Also saved to accounts.json — do NOT commit that file; it is git-ignored.)")
