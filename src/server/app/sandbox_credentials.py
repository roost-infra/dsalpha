"""User-level sandbox provider credentials (BYOK).

Endpoints:
- GET    /api/v1/users/me/sandbox-credentials        — per-kind state, keys masked
- PUT    /api/v1/users/me/sandbox-credentials/{kind} — save the caller's key
- DELETE /api/v1/users/me/sandbox-credentials/{kind} — remove it, back to the
                                                       deployment default

A key is encrypted at rest and never returned in plaintext. Only the provider
the deployment knows how to create computers on is listed, so a user cannot
save a key for a backend the server cannot build.
"""

import logging
import os
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from src.server.database.encryption import decrypt_secret, encrypt_secret
from src.server.database.sandbox_credentials import (
    SUPPORTED_KINDS,
    delete_sandbox_credential,
    list_sandbox_credentials,
    save_sandbox_credential,
)
from src.server.utils.api import CurrentUserId

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sandbox credentials"])

# The deployment environment variable that holds the platform's own key for a
# kind, so the page can say whether the platform still provides one.
_DEPLOYMENT_KEY_ENV = {"daytona": "DAYTONA_API_KEY"}


def _mask(key: str) -> str:
    if len(key) < 8:
        return "****"
    return f"{key[:3]}...{key[-4:]}"


def _deployment_available(kind: str) -> bool:
    return bool(os.getenv(_DEPLOYMENT_KEY_ENV.get(kind, ""), "").strip())


def _summarize(row: dict) -> dict:
    try:
        masked = _mask(decrypt_secret(row["api_key_encrypted"]))
    except ValueError:
        # A rotated BYOK_ENCRYPTION_KEY: the row is unusable, and saying so is
        # better than showing a key nobody can decrypt.
        masked = "****"
    updated_at = row.get("updated_at")
    return {
        "kind": row["kind"],
        "configured": True,
        "masked_key": masked,
        "base_url": row.get("base_url"),
        "updated_at": updated_at.isoformat() if updated_at else None,
        "deployment_available": _deployment_available(row["kind"]),
    }


def _unconfigured(kind: str) -> dict:
    return {
        "kind": kind,
        "configured": False,
        "masked_key": None,
        "base_url": None,
        "updated_at": None,
        "deployment_available": _deployment_available(kind),
    }


@router.get("/api/v1/users/me/sandbox-credentials")
async def get_sandbox_credentials(user_id: CurrentUserId):
    """Every supported provider and whether the caller brought their own key."""
    rows = {row["kind"]: row for row in await list_sandbox_credentials(user_id)}
    return {
        "providers": [
            _summarize(rows[kind]) if kind in rows else _unconfigured(kind)
            for kind in SUPPORTED_KINDS
        ]
    }


class SandboxCredentialRequest(BaseModel):
    api_key: str
    base_url: Optional[str] = None

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("api_key must not be empty")
        if len(v) > 4096:
            raise ValueError("api_key must be under 4096 chars")
        if not v.isascii():
            raise ValueError("api_key must be ASCII")
        return v

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 512:
            raise ValueError("base_url must be under 512 chars")
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("base_url must be an http(s) URL")
        return v


@router.put("/api/v1/users/me/sandbox-credentials/{kind}")
async def put_sandbox_credential(
    kind: str, body: SandboxCredentialRequest, user_id: CurrentUserId
):
    """Save the caller's own key for one provider."""
    if kind not in SUPPORTED_KINDS:
        raise HTTPException(
            status_code=404, detail=f"Unsupported sandbox provider: {kind}"
        )
    row = await save_sandbox_credential(
        user_id,
        kind,
        api_key_encrypted=encrypt_secret(body.api_key),
        base_url=body.base_url,
    )
    logger.info("sandbox credential saved user=%s kind=%s", user_id, kind)
    return _summarize(row)


@router.delete("/api/v1/users/me/sandbox-credentials/{kind}")
async def remove_sandbox_credential(kind: str, user_id: CurrentUserId):
    """Forget the caller's own key; new computers use the deployment's again.

    Machines already created with the old key keep working, since their
    provider_config holds its own encrypted copy.
    """
    if kind not in SUPPORTED_KINDS:
        raise HTTPException(
            status_code=404, detail=f"Unsupported sandbox provider: {kind}"
        )
    removed = await delete_sandbox_credential(user_id, kind)
    logger.info(
        "sandbox credential removed user=%s kind=%s removed=%s",
        user_id,
        kind,
        removed,
    )
    return {
        "kind": kind,
        "configured": False,
        "removed": removed,
        "deployment_available": _deployment_available(kind),
    }
