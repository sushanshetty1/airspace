"""The video's user in the local accounts graph, and a session cookie for it, written to .stack-data/cookie.

    uv run --project server python video/capture/signin.py   (with the stack's environment: capture/stack.mjs)

GitHub sign-in needs a real OAuth app; the local stack uses the same signed cookie a GitHub sign-in sets, for the
owner's public GitHub profile.
"""

import os
from pathlib import Path

from falkordb import FalkorDB

from airspace.cloud import session
from airspace.cloud.accounts import Accounts

DATA = Path(__file__).resolve().parents[1] / ".stack-data"

db = FalkorDB(host="localhost", port=6379)
accounts = Accounts(db)
profile = {"id": 157783413, "login": "sushanshetty1", "name": "Sushan Shetty",
           "avatar_url": "https://avatars.githubusercontent.com/u/157783413?v=4"}
user_id = accounts.upsert_user(profile)
(DATA / "cookie").write_text(session.sign(user_id, os.environ["AIRSPACE_SECRET"]))
print("signed in as", profile["login"])
