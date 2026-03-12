#!/usr/bin/env python3
"""Smoke test for dance run_action.py client/server entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


def _run(args: list[str]) -> dict:
    out = subprocess.check_output(args, text=True).strip()
    return json.loads(out)


def main() -> None:
    script = Path(__file__).resolve().parent / "dance" / "run_action.py"

    status = _run(["python3", str(script), '{"action":"dance.status"}'])
    assert status["state"] in {"idle", "running", "paused", "stopping", "stopped", "error", "starting"}

    shutdown = _run(["python3", str(script), "--shutdown"])
    assert shutdown.get("ok") is True

    print("dance action cli tests passed")


if __name__ == "__main__":
    main()
