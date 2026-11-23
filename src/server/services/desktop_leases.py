"""One-use browser tickets and cross-worker desktop control."""

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import uuid4

from src.utils.cache.redis_cache import get_cache_client

TICKET_SECONDS = 60
LEASE_SECONDS = 20
Role = Literal["control", "view"]


class DesktopBusy(Exception):
    pass


class DesktopRevoked(Exception):
    pass


@dataclass(frozen=True)
class Session:
    session_id: str
    computer_id: str
    user_id: str
    provider_ref: str
    role: Role
    transport: str
    running_since: str = ""


def _prefix(computer_id: str) -> str:
    return f"desktop:{{{computer_id}}}:"


def _ticket_key(computer_id: str, ticket: str) -> str:
    digest = hashlib.sha256(ticket.encode()).hexdigest()
    return f"{_prefix(computer_id)}ticket:{digest}"


def _keys(session: Session) -> list[str]:
    prefix = _prefix(session.computer_id)
    return [prefix + "holder", prefix + "generation", prefix + "session:" + session.session_id]


# The generation changes on every claim, even a control session that starts
# and ends during a single screenshot. Such a frame must never reach a viewer.
_ISSUE = """
local holder = redis.call('get', KEYS[1])
if holder and ARGV[2] ~= 'takeover' then return 0 end
local generation = redis.call('get', KEYS[2])
if ARGV[1] == 'control' then
    redis.call('set', KEYS[1], ARGV[3], 'EX', ARGV[4])
    generation = ARGV[3]
elseif not generation then
    generation = ARGV[3]
end
redis.call('set', KEYS[2], generation, 'EX', ARGV[5])
redis.call('set', KEYS[3], generation, 'EX', ARGV[4])
redis.call('set', KEYS[4], ARGV[6], 'EX', ARGV[4])
return 1
"""

_CHECK = """
local generation = redis.call('get', KEYS[3])
if not generation or generation ~= redis.call('get', KEYS[2]) then return 0 end
local holder = redis.call('get', KEYS[1])
if ARGV[1] == 'view' and holder then return 0 end
if ARGV[1] == 'control' and holder ~= ARGV[2] then return 0 end
if ARGV[3] ~= '0' then
    if holder then redis.call('expire', KEYS[1], ARGV[3]) end
    redis.call('expire', KEYS[3], ARGV[3])
    redis.call('expire', KEYS[2], ARGV[4])
end
return 1
"""

_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then redis.call('del', KEYS[1]) end
return redis.call('del', KEYS[2])
"""


async def issue(computer: dict, role: Role, transport: str, *, takeover: bool) -> tuple[Session, str]:
    session = Session(str(uuid4()), str(computer["computer_id"]), computer["user_id"],
                      str(computer["provider_ref"]), role, transport,
                      str(computer.get("running_since") or ""))
    ticket = secrets.token_urlsafe(32)
    keys = [*_keys(session), _ticket_key(session.computer_id, ticket)]
    ok = await get_cache_client().client.eval(
        _ISSUE, len(keys), *keys, role, "takeover" if takeover else "", session.session_id,
        TICKET_SECONDS, TICKET_SECONDS * 2, json.dumps(asdict(session)),
    )
    if not ok:
        raise DesktopBusy
    return session, ticket


async def redeem(computer_id: str, ticket: str) -> Session | None:
    raw = await get_cache_client().client.getdel(_ticket_key(computer_id, ticket))
    if raw is None:
        return None
    return Session(**json.loads(raw))


async def check(session: Session, *, renew: bool = False) -> None:
    keys = _keys(session)
    ok = await get_cache_client().client.eval(
        _CHECK, len(keys), *keys, session.role, session.session_id,
        LEASE_SECONDS if renew else 0, TICKET_SECONDS * 2,
    )
    if not ok:
        raise DesktopRevoked


async def release(computer_id: str, session_id: str) -> None:
    prefix = _prefix(computer_id)
    await get_cache_client().client.eval(
        _RELEASE, 2, prefix + "holder", prefix + "session:" + session_id, session_id,
    )


async def viewer_generation(computer_id: str) -> str | bytes | None:
    prefix = _prefix(computer_id)
    holder, generation = await get_cache_client().client.mget(prefix + "holder", prefix + "generation")
    if holder is not None:
        raise DesktopBusy
    return generation
