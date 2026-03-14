#!/usr/bin/env python3
"""CLI entrypoint for social and short emote actions."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
from typing import Any, Callable, Mapping

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from demo_gesture_player import DemoGesturePlayer

DEFAULT_STATE_PATH = "/tmp/openhand-emote-state.json"
DEFAULT_LOCK_PATH = "/tmp/openhand-emote.lock"
DEFAULT_DANCE_SOCKET = "/tmp/openhand-dance.sock"
BUSY_DANCE_STATES = {"starting", "running", "paused", "stopping"}

GREETING_PATTERNS = (
    re.compile(r"\b(hello|hi|hey)\b", re.IGNORECASE),
    re.compile(r"哈(喽|啰|罗|咯)?", re.IGNORECASE),
    re.compile(r"你好", re.IGNORECASE),
    re.compile(r"在吗|在不在|有人吗", re.IGNORECASE),
)


@dataclass(frozen=True)
class EmotePreset:
    """Runtime preset for a short emote sequence."""

    unit_sequence: tuple[str, ...]
    repeat: int
    interval_s: float
    hold_ms: int
    settle_s: float
    end_gesture: str | None


PRESETS: dict[str, EmotePreset] = {
    "greet_wave_lr_v1": EmotePreset(
        unit_sequence=("wave_left", "wave_right"),
        repeat=2,
        interval_s=1.0,
        hold_ms=280,
        settle_s=0.2,
        end_gesture="open_hand",
    ),
}


def parse_social_intent(text: str) -> dict[str, Any]:
    """Classify short social text into one intent."""
    content = str(text or "").strip()
    if not content:
        return {"intent": "none", "confidence": 0.0, "matched": False}

    matched = any(pattern.search(content) for pattern in GREETING_PATTERNS)
    if matched:
        confidence = 0.95 if len(content) <= 10 else 0.88
        return {
            "intent": "greeting.ping",
            "confidence": confidence,
            "matched": True,
        }

    return {"intent": "none", "confidence": 0.15, "matched": False}


def _recv_all(conn: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        data = conn.recv(4096)
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


def _send_socket_payload(socket_path: str, payload: dict[str, Any], timeout_s: float = 0.5) -> dict[str, Any]:
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


def query_dance_status(socket_path: str = DEFAULT_DANCE_SOCKET) -> dict[str, Any] | None:
    """Best-effort query of dance runtime state."""
    if not Path(socket_path).exists():
        return None
    try:
        result = _send_socket_payload(socket_path, {"action": "dance.status"})
        if isinstance(result, dict):
            return result
    except Exception:
        return None
    return None


class LockBusyError(RuntimeError):
    """Raised when another emote process is already active."""


class EmoteService:
    """Action router for social.reply and emote.play/status."""

    def __init__(
        self,
        player_factory: Callable[[], Any] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        dance_status_getter: Callable[[], Mapping[str, Any] | None] | None = None,
        state_path: str = DEFAULT_STATE_PATH,
        lock_path: str = DEFAULT_LOCK_PATH,
    ) -> None:
        self._player_factory = player_factory or DemoGesturePlayer
        self._sleep = sleep_fn or time.sleep
        self._dance_status_getter = dance_status_getter or query_dance_status
        self._state_path = Path(state_path)
        self._lock_path = Path(lock_path)

    def handle_action(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip().lower()
        if not action:
            raise ValueError("payload.action is required")

        if action in {"social.reply", "reply"}:
            return self._handle_social_reply(payload)
        if action in {"emote.play", "play"}:
            return self._handle_emote_play(payload)
        if action in {"emote.status", "status"}:
            return self._handle_status()
        if action in {"emote.list", "list"}:
            return {"ok": True, "presets": sorted(PRESETS.keys())}

        raise ValueError(f"unsupported action: {action}")

    def _handle_social_reply(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or payload.get("prompt") or "").strip()
        intent = parse_social_intent(text)
        if not intent["matched"]:
            return {
                "ok": True,
                "intent": intent["intent"],
                "confidence": intent["confidence"],
                "matched": False,
                "executed": False,
                "state": "idle",
            }

        play_payload: dict[str, Any] = {
            "action": "emote.play",
            "preset_id": payload.get("preset_id") or "greet_wave_lr_v1",
            "if_busy": payload.get("if_busy") or "drop",
            "repeat": payload.get("repeat"),
            "interval_s": payload.get("interval_s"),
            "hold_ms": payload.get("hold_ms"),
            "settle_s": payload.get("settle_s"),
        }
        result = self._handle_emote_play(play_payload)
        result["intent"] = intent["intent"]
        result["confidence"] = intent["confidence"]
        result["matched"] = True
        return result

    def _handle_emote_play(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        preset_id = str(payload.get("preset_id") or "greet_wave_lr_v1").strip()
        preset = PRESETS.get(preset_id)
        if preset is None:
            raise ValueError(f"unknown preset_id: {preset_id}")

        repeat = int(payload.get("repeat") or preset.repeat)
        repeat = max(1, min(8, repeat))
        interval_s = float(payload.get("interval_s") if payload.get("interval_s") is not None else preset.interval_s)
        interval_s = max(0.0, min(10.0, interval_s))
        hold_ms = int(payload.get("hold_ms") or preset.hold_ms)
        hold_ms = max(0, min(5000, hold_ms))
        settle_s = float(payload.get("settle_s") if payload.get("settle_s") is not None else preset.settle_s)
        settle_s = max(0.0, min(2.0, settle_s))
        if_busy = str(payload.get("if_busy") or "drop").strip().lower()

        dance_status = self._dance_status_getter()
        dance_state = str((dance_status or {}).get("state") or "").lower()
        if dance_state in BUSY_DANCE_STATES:
            if if_busy == "error":
                raise RuntimeError(f"dance runtime is busy: {dance_state}")
            return {
                "ok": True,
                "executed": False,
                "state": "busy",
                "reason": "dance_active",
                "dance_state": dance_state,
                "preset_id": preset_id,
            }

        try:
            with self._exclusive_lock():
                self._write_state({"state": "running", "preset_id": preset_id, "started_at": time.time()})
                try:
                    self._play_sequence(
                        unit_sequence=preset.unit_sequence,
                        repeat=repeat,
                        interval_s=interval_s,
                        hold_ms=hold_ms,
                        settle_s=settle_s,
                        end_gesture=preset.end_gesture,
                    )
                except Exception as exc:
                    self._write_state(
                        {
                            "state": "error",
                            "preset_id": preset_id,
                            "error": str(exc),
                            "failed_at": time.time(),
                        }
                    )
                    raise
        except LockBusyError:
            if if_busy == "error":
                raise RuntimeError("emote runtime is busy")
            return {
                "ok": True,
                "executed": False,
                "state": "busy",
                "reason": "emote_active",
                "preset_id": preset_id,
            }

        self._write_state(
            {
                "state": "completed",
                "preset_id": preset_id,
                "completed_at": time.time(),
                "repeat": repeat,
                "interval_s": interval_s,
            }
        )
        return {
            "ok": True,
            "executed": True,
            "state": "completed",
            "preset_id": preset_id,
            "repeat": repeat,
            "interval_s": interval_s,
            "unit_sequence": list(preset.unit_sequence),
        }

    def _play_sequence(
        self,
        unit_sequence: tuple[str, ...],
        repeat: int,
        interval_s: float,
        hold_ms: int,
        settle_s: float,
        end_gesture: str | None,
    ) -> None:
        player = self._player_factory()
        try:
            if hasattr(player, "start"):
                player.start()
            for cycle in range(repeat):
                for gesture in unit_sequence:
                    player.play_gesture(
                        gesture,
                        hold_ms=hold_ms,
                        enable=True,
                        settle_s=settle_s,
                        relax_after_settle=True,
                    )
                if cycle < repeat - 1 and interval_s > 0:
                    self._sleep(interval_s)
            if end_gesture:
                player.play_gesture(
                    end_gesture,
                    hold_ms=min(hold_ms, 300),
                    enable=True,
                    settle_s=settle_s,
                    relax_after_settle=True,
                )
        finally:
            if hasattr(player, "close"):
                player.close()

    @contextmanager
    def _exclusive_lock(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LockBusyError("emote runtime lock is busy") from exc
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _handle_status(self) -> dict[str, Any]:
        state = self._read_state()
        state.setdefault("state", "idle")
        state["ok"] = True
        dance = self._dance_status_getter()
        if isinstance(dance, Mapping):
            state["dance_state"] = str(dance.get("state") or "")
        return state

    def _read_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return {}
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, data: Mapping[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(dict(data), ensure_ascii=False),
            encoding="utf-8",
        )


def _parse_payload(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Social + emote action entrypoint")
    parser.add_argument("payload", nargs="?", help="JSON payload object, e.g. '{\"action\":\"social.reply\",\"text\":\"哈喽\"}'")
    parser.add_argument("--stdin", action="store_true", help="Read JSON payload from stdin")
    args = parser.parse_args()

    raw = sys.stdin.read().strip() if args.stdin else (args.payload or "").strip()
    if not raw:
        raise SystemExit("missing payload: pass JSON arg or use --stdin")

    payload = _parse_payload(raw)
    service = EmoteService()
    try:
        response = service.handle_action(payload)
    except Exception as exc:
        response = {"ok": False, "error": str(exc)}

    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
