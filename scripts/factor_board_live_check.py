"""Live check of the Factor Board router against the running factor-miner.

Not a unit test — it exercises the real service (the miner's qlib panel and
sandbox), which is the only way to know the transport, the async job handoff and
the verdict all agree with what the miner actually returns.
"""

import os
import sys
import time

os.environ.setdefault("FACTOR_MINER_LICENSE_KEY", open("/tmp/.fkey").read().strip())
os.environ.setdefault("HOST_MODE", "oss")

sys.path.insert(0, "/Users/hjx/LangAlpha-worktrees/factor-board")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.server.app.factors import router  # noqa: E402

app = FastAPI()
app.include_router(router)


def main() -> int:
    with TestClient(app) as client:
        health = client.get("/api/v1/factors/health")
        print("health:", health.status_code, health.json())

        templates = client.get("/api/v1/factors/templates")
        body = templates.json()
        print("templates:", templates.status_code, [t["key"] for t in body["templates"]])
        code = body["templates"][0]["code"]

        started = client.post(
            "/api/v1/factors/detections",
            json={"name": "reversal_20", "code": code, "debug": True, "include_oos": True},
        )
        print("submit:", started.status_code, started.json()["run_id"], started.json()["status"])
        run_id = started.json()["run_id"]

        deadline = time.time() + 1500
        last = None
        while time.time() < deadline:
            run = client.get(f"/api/v1/factors/detections/{run_id}").json()
            snapshot = (
                run["status"],
                run["current_stage"],
                [(s["key"], s["state"], s["detail"]) for s in run["stages"]],
            )
            if snapshot != last:
                print("poll:", snapshot, flush=True)
                last = snapshot
            if run["status"] in ("done", "failed"):
                print("VERDICT:", run["verdict"])
                print("FINDINGS:", run["findings"])
                return 0 if run["status"] == "done" else 1
            time.sleep(5)
        print("TIMEOUT waiting for detection")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
