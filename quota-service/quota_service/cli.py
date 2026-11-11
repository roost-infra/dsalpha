"""``quota-admin``: a thin CLI over the admin JSON API.

Same operations as the admin page, for scripts and incident handling. Reads
``QUOTA_ADMIN_URL`` (default ``http://127.0.0.1:8080``) and ``ADMIN_TOKEN``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _base() -> str:
    return os.environ.get("QUOTA_ADMIN_URL", "http://127.0.0.1:8080").rstrip("/")


def _call(method: str, path: str, body: dict | None = None) -> dict:
    token = os.environ.get("ADMIN_TOKEN", "").strip()
    if not token:
        sys.exit("ADMIN_TOKEN is required")
    request = urllib.request.Request(
        _base() + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}")
    except urllib.error.URLError as exc:
        sys.exit(f"cannot reach {_base()}: {exc.reason}")


def _print(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="quota-admin", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("plans", help="list plans").set_defaults(handler=lambda _: _print(_call("GET", "/admin/api/plans")))

    assign = sub.add_parser("assign", help="assign a plan to a user")
    assign.add_argument("user_id")
    assign.add_argument("plan_code")
    assign.add_argument("--note", default=None)
    assign.add_argument("--grant-month", action="store_true")

    topup = sub.add_parser("topup", help="add credits")
    topup.add_argument("user_id")
    topup.add_argument("credits", type=float)
    topup.add_argument("--note", default=None)

    adjust = sub.add_parser("adjust", help="correct a balance (may be negative)")
    adjust.add_argument("user_id")
    adjust.add_argument("delta", type=float)
    adjust.add_argument("--reason", default="adjust", choices=["adjust"])
    adjust.add_argument("--note", default=None)

    usage = sub.add_parser("usage", help="show a user's bundle")
    usage.add_argument("user_id")

    ledger = sub.add_parser("ledger", help="recent ledger entries")
    ledger.add_argument("--user", default="")
    ledger.add_argument("--reason", default="")
    ledger.add_argument("--page-size", type=int, default=50)

    tokens = sub.add_parser("tokens", help="per-user token usage")
    tokens.add_argument("user_id")
    tokens.add_argument("--days", type=int, default=30)

    leases = sub.add_parser("leases", help="active leases of a user")
    leases.add_argument("user_id")

    args = parser.parse_args(argv)

    if args.command == "assign":
        _print(_call("POST", f"/admin/api/users/{args.user_id}/plan", {
            "plan_code": args.plan_code,
            "note": args.note,
            "grant_month": args.grant_month,
        }))
    elif args.command == "topup":
        _print(_call("POST", f"/admin/api/users/{args.user_id}/credits", {
            "delta": args.credits,
            "reason": "topup",
            "note": args.note,
        }))
    elif args.command == "adjust":
        _print(_call("POST", f"/admin/api/users/{args.user_id}/credits", {
            "delta": args.delta,
            "reason": "adjust",
            "note": args.note,
        }))
    elif args.command == "usage":
        bundle = _call("GET", f"/admin/api/users/{args.user_id}")
        _print({
            "user": bundle["user"],
            "leases": bundle["leases"],
            "recent_ledger": bundle["ledger"],
        })
    elif args.command == "ledger":
        _print(_call(
            "GET",
            f"/admin/api/ledger?user_id={args.user}&reason={args.reason}"
            f"&page_size={args.page_size}",
        ))
    elif args.command == "tokens":
        _print(_call(
            "GET", f"/admin/api/users/{args.user_id}/usage?days={args.days}"
        ))
    elif args.command == "leases":
        bundle = _call("GET", f"/admin/api/users/{args.user_id}")
        _print(bundle["leases"])
    else:
        _print(_call("GET", "/admin/api/plans"))


if __name__ == "__main__":
    main()
