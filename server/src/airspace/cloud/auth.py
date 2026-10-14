"""GitHub sign-in and the session it leaves behind.

/auth/github/login sends the browser to GitHub with a random state, also kept in a short-lived cookie.
/auth/github/callback checks the two match (so another site cannot finish a sign-in for you), trades the code for
a token, reads the profile, upserts the User and sets the signed session cookie. The token is used once and never
stored: the profile is all Airspace needs.
"""

import hmac
import logging
import secrets
from urllib.parse import quote, unquote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from airspace.api.app import ApiError
from airspace.cloud import session

log = logging.getLogger("airspace.cloud")

STATE_COOKIE = "airspace_oauth_state"
STATE_MAX_AGE = 600
DEFAULT_NEXT = "/app"
AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
NOT_CONFIGURED = "Sign-in is not configured on this server."
SIGN_IN_FIRST = "Sign in first."
NEEDS_HEADER = "This request needs the header X-Airspace: 1."


def safe_next(value: str | None) -> str:
    """A same-site path to return to after sign-in. Anything else (another host, //host, /\\host) becomes /app."""
    if not value or len(value) > 512 or not value.startswith("/") or value.startswith("//"):
        return DEFAULT_NEXT
    if "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return DEFAULT_NEXT
    return value


def current_user(cloud, request: Request) -> str | None:
    """The signed-in user's id from the session cookie, or None."""
    if not cloud.config.sessions:
        return None
    return session.verify(request.cookies.get(session.COOKIE), cloud.config.secret, now=cloud.clock())


def require_user(cloud, request: Request) -> str:
    """The signed-in user's id. A POST or DELETE also needs X-Airspace: 1, which a cross-site form cannot send."""
    user_id = current_user(cloud, request)
    if user_id is None:
        raise ApiError(401, SIGN_IN_FIRST)
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get("x-airspace") != "1":
        raise ApiError(403, NEEDS_HEADER)
    return user_id


def _secure(cloud, request: Request) -> bool:
    url = cloud.config.public_url or str(request.base_url)
    return url.startswith("https://")


def _callback_url(cloud, request: Request) -> str:
    base = cloud.config.public_url or str(request.base_url).rstrip("/")
    return f"{base}/auth/github/callback"


def _github_profile(cloud, request: Request, code: str) -> dict:
    """The GitHub profile for an authorization code. Raises ApiError(502) when GitHub does not give one."""
    cfg = cloud.config
    try:
        with cloud.http() as client:
            r = client.post(
                TOKEN_URL,
                data={
                    "client_id": cfg.github_client_id,
                    "client_secret": cfg.github_client_secret,
                    "code": code,
                    "redirect_uri": _callback_url(cloud, request),
                },
                headers={"Accept": "application/json"},
            )
            token = r.json().get("access_token") if r.status_code == 200 else None
            if not token:
                log.warning("airspace: GitHub token exchange failed (%s)", r.status_code)
                raise ApiError(502, "GitHub did not accept the sign-in. Try again.")
            r = client.get(
                USER_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            )
            profile = r.json() if r.status_code == 200 else None
    except ApiError:
        raise
    except Exception as e:
        log.warning("airspace: GitHub unreachable during sign-in (%s)", type(e).__name__)
        raise ApiError(502, "GitHub could not be reached. Try again.") from e
    if not isinstance(profile, dict) or not isinstance(profile.get("id"), int) or not profile.get("login"):
        raise ApiError(502, "GitHub did not return a profile. Try again.")
    return profile


def router(cloud) -> APIRouter:
    r = APIRouter()

    def not_configured() -> JSONResponse:
        return JSONResponse(status_code=503, content={"error": NOT_CONFIGURED})

    @r.get("/auth/github/login")
    def login(request: Request, next: str | None = None):
        if not cloud.config.signin:
            return not_configured()
        state = secrets.token_urlsafe(24)
        query = urlencode({
            "client_id": cloud.config.github_client_id,
            "redirect_uri": _callback_url(cloud, request),
            "scope": "read:user",
            "state": state,
            "allow_signup": "true",
        })
        resp = RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=302)
        # The return path rides along in the state cookie; it is checked again on the way back.
        resp.set_cookie(
            STATE_COOKIE, f"{state}.{quote(safe_next(next), safe='')}", max_age=STATE_MAX_AGE, httponly=True,
            secure=_secure(cloud, request), samesite="lax", path="/",
        )
        return resp

    @r.get("/auth/github/callback")
    def callback(request: Request, code: str = "", state: str = ""):
        if not cloud.config.signin:
            return not_configured()
        stored = request.cookies.get(STATE_COOKIE) or ""
        expected, _, encoded_next = stored.partition(".")
        if not expected or not state or not hmac.compare_digest(expected.encode(), state.encode()):
            return JSONResponse(status_code=400, content={"error": "The sign-in state does not match. Sign in again."})
        if not code:
            return JSONResponse(status_code=400, content={"error": "GitHub did not return a code. Sign in again."})
        profile = _github_profile(cloud, request, code)
        user_id = cloud.accounts().upsert_user(profile)
        resp = RedirectResponse(safe_next(unquote(encoded_next)), status_code=302)
        resp.delete_cookie(STATE_COOKIE, path="/")
        resp.set_cookie(
            session.COOKIE, session.sign(user_id, cloud.config.secret, now=cloud.clock()), max_age=session.MAX_AGE,
            httponly=True, secure=_secure(cloud, request), samesite="lax", path="/",
        )
        return resp

    @r.post("/auth/logout")
    def logout(request: Request):
        if request.headers.get("x-airspace") != "1":
            raise ApiError(403, NEEDS_HEADER)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(session.COOKIE, path="/", httponly=True, secure=_secure(cloud, request), samesite="lax")
        return resp

    @r.get("/api/me")
    def me(request: Request) -> dict:
        signin = cloud.config.signin
        user_id = current_user(cloud, request)
        if user_id is None:
            return {"user": None, "workspaces": [], "signin": signin}
        accounts = cloud.accounts()
        user = accounts.user(user_id)
        if user is None:
            return {"user": None, "workspaces": [], "signin": signin}
        return {"user": user, "workspaces": accounts.workspaces(user_id), "signin": signin}

    return r
