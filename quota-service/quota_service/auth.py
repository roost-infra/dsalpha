"""Credential checks for the two very different callers of this service.

* dsalpha calls ``/api/auth/*`` with the shared service token plus the user
  id it is acting for (``X-Service-Token`` / ``X-User-Id``).
* A human administrator calls ``/admin/*`` with a signed session cookie made
  from ``ADMIN_TOKEN`` (or a Bearer token, for scripts).
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import Settings

SERVICE_HEADER = "X-Service-Token"
USER_HEADER = "X-User-Id"
ADMIN_COOKIE = "qa_admin"
_ADMIN_SALT = "langalpha-quota-admin"


def _equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


def service_user(request: Request) -> str:
    """The user dsalpha is acting for. Raises 401 when the caller is not it."""
    settings = settings_of(request)
    token = request.headers.get(SERVICE_HEADER, "")
    if not token or not _equal(token, settings.internal_service_token):
        raise HTTPException(status_code=401, detail="invalid service token")
    user_id = request.headers.get(USER_HEADER, "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="missing X-User-Id")
    return user_id


def serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.cookie_secret, salt=_ADMIN_SALT)


def issue_admin_cookie(settings: Settings, actor: str = "admin") -> str:
    return serializer(settings).dumps({"actor": actor})


def admin_actor(request: Request) -> str:
    """The administrator behind this request, from the cookie or a Bearer token."""
    settings = settings_of(request)
    raw = request.cookies.get(ADMIN_COOKIE, "")
    if raw:
        try:
            data = serializer(settings).loads(
                raw, max_age=settings.cookie_max_age_seconds
            )
        except (BadSignature, SignatureExpired):
            raise HTTPException(status_code=401, detail="admin session expired") from None
        return str(data.get("actor", "admin"))

    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token and _equal(token, settings.admin_token):
        return "token"
    raise HTTPException(status_code=401, detail="admin login required")
