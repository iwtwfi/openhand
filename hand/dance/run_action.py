#!/usr/bin/env python3
"""CLI entrypoint for dance actions.

Client mode:
  python3 run_action.py '{"action":"dance.status"}'

Server mode:
  python3 run_action.py --serve

By default client mode auto-starts a background server if not running.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
HAND_DIR = THIS_DIR.parent
if str(HAND_DIR) not in sys.path:
    sys.path.insert(0, str(HAND_DIR))

from dance.api import DanceService

DEFAULT_SOCKET = "/tmp/openhand-dance.sock"
DEFAULT_PID = "/tmp/openhand-dance.pid"


class ServerStop(Exception):
    """Raised to break server loop on shutdown request."""


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return


def _recv_all(conn: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        data = conn.recv(4096)
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


def _send_payload(socket_path: str, payload: dict[str, Any], timeout_s: float = 3.0) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout_s)
        conn.connect(socket_path)
        conn.sendall(raw)
        conn.shutdown(socket.SHUT_WR)
        resp_raw = _recv_all(conn)
    if not resp_raw:
        return {"ok": False, "error": "empty response"}
    return json.loads(resp_raw.decode("utf-8"))


def _is_server_alive(socket_path: str) -> bool:
    if not Path(socket_path).exists():
        return False
    try:
        _send_payload(socket_path, {"action": "dance.status"}, timeout_s=1.0)
        return True
    except Exception:
        return False


def _ensure_server(socket_path: str, pid_path: str, startup_timeout_s: float = 3.0) -> None:
    if _is_server_alive(socket_path):
        return

    _safe_unlink(socket_path)
    cmd = [
        sys.executable,
        str(THIS_DIR / "run_action.py"),
        "--serve",
        "--socket",
        socket_path,
        "--pid",
        pid_path,
    ]
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.monotonic() + startup_timeout_s
    while time.monotonic() < deadline:
        if _is_server_alive(socket_path):
            return
        time.sleep(0.05)

    raise RuntimeError("failed to start dance action daemon")


def _handle_request(service: DanceService, payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().lower()
    if action in {"dance.shutdown", "shutdown", "__shutdown__"}:
        try:
            service.handle_action({"action": "dance.stop"})
        except Exception:
            pass
        raise ServerStop()

    return service.handle_action(payload)


def _run_server(socket_path: str, pid_path: str) -> int:
    _safe_unlink(socket_path)
    Path(socket_path).parent.mkdir(parents=True, exist_ok=True)

    service = DanceService(enable_audio=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    os.chmod(socket_path, 0o600)
    server.listen(8)

    Path(pid_path).write_text(str(os.getpid()), encoding="utf-8")

    try:
        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    raw = _recv_all(conn)
                    if not raw:
                        response = {"ok": False, "error": "empty payload"}
                    else:
                        payload = json.loads(raw.decode("utf-8"))
                        if not isinstance(payload, dict):
                            raise ValueError("payload must be JSON object")
                        response = _handle_request(service, payload)
                except ServerStop:
                    response = {"ok": True, "state": "shutting_down"}
                    conn.sendall(json.dumps(response, ensure_ascii=False).encode("utf-8"))
                    return 0
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}

                conn.sendall(json.dumps(response, ensure_ascii=False).encode("utf-8"))
    finally:
        try:
            server.close()
        finally:
            _safe_unlink(socket_path)
            _safe_unlink(pid_path)


def _parse_payload(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Dance action client/server entrypoint")
    parser.add_argument("payload", nargs="?", help="JSON payload object, e.g. '{\"action\":\"dance.status\"}'")
    parser.add_argument("--socket", default=DEFAULT_SOCKET, help=f"Unix socket path (default: {DEFAULT_SOCKET})")
    parser.add_argument("--pid", default=DEFAULT_PID, help=f"PID file path (default: {DEFAULT_PID})")
    parser.add_argument("--serve", action="store_true", help="Run as background action server")
    parser.add_argument("--stdin", action="store_true", help="Read JSON payload from stdin")
    parser.add_argument("--shutdown", action="store_true", help="Shutdown running daemon")
    args = parser.parse_args()

    if args.serve:
        return _run_server(args.socket, args.pid)

    if args.shutdown:
        _ensure_server(args.socket, args.pid)
        resp = _send_payload(args.socket, {"action": "dance.shutdown"})
        print(json.dumps(resp, ensure_ascii=False))
        return 0

    if args.stdin:
        raw = sys.stdin.read().strip()
    else:
        raw = (args.payload or "").strip()

    if not raw:
        raise SystemExit("missing payload: pass JSON arg or use --stdin")

    payload = _parse_payload(raw)
    _ensure_server(args.socket, args.pid)
    response = _send_payload(args.socket, payload)
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
