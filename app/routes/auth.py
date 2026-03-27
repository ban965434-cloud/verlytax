"""
Verlytax OS v4 — Dashboard Authentication
Single-user (Delta / CEO) login gate. No database — credentials from env vars.
Session token: HMAC-SHA256 signed, stored in httpOnly cookie (8-hour expiry).
"""

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

_SECRET     = os.getenv("SECRET_KEY", "dev-secret-change-me")
_USERNAME   = os.getenv("DASHBOARD_USERNAME", "delta")
_PASSWORD   = os.getenv("DASHBOARD_PASSWORD", "")
_COOKIE     = "vx_session"
_TTL        = 8 * 3600  # 8 hours


# ── Token helpers ──────────────────────────────────────────────────────────────

def _create_token(username: str) -> str:
    payload = json.dumps({"u": username, "iat": int(time.time()), "exp": int(time.time()) + _TTL})
    sig = hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_session(token: str | None) -> bool:
    if not token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = decoded.rsplit("|", 1)
        expected = hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        data = json.loads(payload)
        return int(data.get("exp", 0)) > int(time.time())
    except Exception:
        return False


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/login")
async def do_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Validate credentials and issue session cookie."""
    user_ok = hmac.compare_digest(username.strip(), _USERNAME)
    pass_ok = hmac.compare_digest(password, _PASSWORD) if _PASSWORD else False

    if not (user_ok and pass_ok):
        # Re-serve login page with error (no redirect to avoid credential leakage in URL)
        login_path = os.path.join(os.path.dirname(__file__), "..", "..", "static", "login.html")
        try:
            with open(login_path) as f:
                html = f.read()
            html = html.replace('id="error-msg" style="display:none"',
                                'id="error-msg" style="display:block"')
        except FileNotFoundError:
            html = "<p>Invalid credentials.</p>"
        return HTMLResponse(html, status_code=401)

    token = _create_token(username.strip())
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        key=_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=os.getenv("APP_ENV") == "production",
        max_age=_TTL,
    )
    return response


@router.post("/logout")
async def do_logout():
    """Clear session cookie and redirect to login."""
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(_COOKIE)
    return response
