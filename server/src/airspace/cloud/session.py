"""The signed session cookie: `<user_id>.<expiry unix>.<hex HMAC-SHA256(secret, user_id + "." + expiry)>`.

The cookie holds no secrets, only who signed in and until when. The signature stops anyone forging another user's
id, and the expiry inside the signed text stops an old cookie living longer than 30 days.
"""

import hashlib
import hmac
import time

COOKIE = "airspace_session"
MAX_AGE = 30 * 24 * 3600


def _mac(secret: str, user_id: str, expiry: int) -> str:
    return hmac.new(secret.encode(), f"{user_id}.{expiry}".encode(), hashlib.sha256).hexdigest()


def sign(user_id: str, secret: str, now: float | None = None, max_age: int = MAX_AGE) -> str:
    if not secret:
        raise ValueError("A session needs a secret.")
    if not user_id or "." in user_id:
        raise ValueError("A user id must be non-empty and contain no dot.")
    expiry = int(time.time() if now is None else now) + max_age
    return f"{user_id}.{expiry}.{_mac(secret, user_id, expiry)}"


def verify(cookie: str | None, secret: str, now: float | None = None) -> str | None:
    """The user id the cookie was signed for, or None when it is missing, forged, malformed or expired."""
    if not cookie or not secret:
        return None
    parts = cookie.split(".")
    if len(parts) != 3:
        return None
    user_id, expiry_text, mac = parts
    if not user_id or not expiry_text.isdigit():
        return None
    expiry = int(expiry_text)
    if not hmac.compare_digest(mac.encode(), _mac(secret, user_id, expiry).encode()):
        return None
    if expiry <= (time.time() if now is None else now):
        return None
    return user_id
