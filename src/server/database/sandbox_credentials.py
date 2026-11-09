"""Per-user sandbox provider credentials (BYOK).

The API key is encrypted app-side (``database/encryption.py``) because a
computer's provider is constructed synchronously and cannot await a database
decryption. Only ciphertext leaves this module; callers that need a mask
decrypt it themselves.
"""

from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row

from src.server.database.pool import get_db_connection

# Providers a user may bring their own key for. SSH machines carry their own
# per-user key flow in ssh_keys; docker runs on this host.
SUPPORTED_KINDS: tuple[str, ...] = ("daytona",)

_COLUMNS = "kind, api_key_encrypted, base_url, created_at, updated_at"


async def list_sandbox_credentials(user_id: str) -> List[Dict[str, Any]]:
    """Every provider kind the user has configured, one row each."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_COLUMNS} FROM user_sandbox_credentials "
                "WHERE user_id = %s ORDER BY kind",
                (user_id,),
            )
            return await cur.fetchall()


async def get_sandbox_credential(user_id: str, kind: str) -> Optional[Dict[str, Any]]:
    """The user's credential for one kind, or None when they rely on the
    deployment's."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_COLUMNS} FROM user_sandbox_credentials "
                "WHERE user_id = %s AND kind = %s",
                (user_id, kind),
            )
            return await cur.fetchone()


async def save_sandbox_credential(
    user_id: str,
    kind: str,
    *,
    api_key_encrypted: str,
    base_url: Optional[str],
) -> Dict[str, Any]:
    """Insert or replace one credential and answer the stored row."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                INSERT INTO user_sandbox_credentials
                    (user_id, kind, api_key_encrypted, base_url)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, kind) DO UPDATE SET
                    api_key_encrypted = EXCLUDED.api_key_encrypted,
                    base_url = EXCLUDED.base_url,
                    updated_at = NOW()
                RETURNING {_COLUMNS}
                """,
                (user_id, kind, api_key_encrypted, base_url),
            )
            return await cur.fetchone()


async def delete_sandbox_credential(user_id: str, kind: str) -> bool:
    """Remove one credential; False when there was none to remove."""
    async with get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM user_sandbox_credentials "
                "WHERE user_id = %s AND kind = %s",
                (user_id, kind),
            )
            return cur.rowcount > 0
