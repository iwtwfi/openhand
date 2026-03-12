#!/usr/bin/env python3
"""Consistency orchestration between vision output and hand gestures.

Business contract:
- If faces.value == gesture.value -> call hand gesture "correct"
- Else -> call hand gesture "wrong"
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from demo_gesture_player import DemoGesturePlayer

VISION_MONITOR_RUN = Path("/home/xu/.openclaw/workspace/skills/vision-monitor/run.sh")


@dataclass
class VisionSample:
    faces: int
    gesture: int
    timestamp_ms: int
    payload: dict[str, Any]


@dataclass
class PipelineResult:
    faces: int
    gesture: int
    consistent: bool
    decision: str
    action_id: str
    driver_gesture: str
    ok: bool
    reason: str
    timestamp_ms: int


class ConsistencyService:
    """Top-level service with only two hand action APIs for business logic."""

    def __init__(
        self,
        hold_ms: int = 500,
        dry_run: bool = False,
        match_gesture: str = "correct",
        mismatch_gesture: str = "wrong",
    ) -> None:
        self.hold_ms = int(hold_ms)
        self.dry_run = bool(dry_run)
        self.match_gesture = str(match_gesture)
        self.mismatch_gesture = str(mismatch_gesture)
        self._player: DemoGesturePlayer | None = None

    def __enter__(self) -> "ConsistencyService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._player is not None:
            self._player.close()
            self._player = None

    def _ensure_player(self) -> DemoGesturePlayer:
        if self._player is None:
            self._player = DemoGesturePlayer()
            self._player.start()
            self._validate_mapped_gestures()
        return self._player

    def _validate_mapped_gestures(self) -> None:
        assert self._player is not None
        available = self._player.gestures
        if self.match_gesture not in available:
            raise ValueError(f"match gesture not found in demo_gestures.yaml: {self.match_gesture}")
        if self.mismatch_gesture not in available:
            raise ValueError(
                f"mismatch gesture not found in demo_gestures.yaml: {self.mismatch_gesture}"
            )

    @staticmethod
    def _extract_last_json_line(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("vision monitor returned empty output")
        return lines[-1]

    def read_vision_sample(self, timeout_s: float = 30.0) -> VisionSample:
        if not VISION_MONITOR_RUN.exists():
            raise FileNotFoundError(f"vision monitor script not found: {VISION_MONITOR_RUN}")

        proc = subprocess.run(
            ["bash", str(VISION_MONITOR_RUN), "read"],
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            check=False,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip() or "unknown error"
            raise RuntimeError(f"vision monitor failed: {stderr}")

        line = self._extract_last_json_line(proc.stdout)
        payload = json.loads(line)
        if not isinstance(payload, dict) or not payload:
            raise RuntimeError("vision monitor returned no valid frame")

        faces = payload.get("faces", {}).get("value")
        gesture = payload.get("gesture", {}).get("value")
        if not isinstance(faces, int) or not isinstance(gesture, int):
            raise RuntimeError("invalid vision payload: missing faces.value or gesture.value")

        ts = payload.get("timestamp_ms")
        if not isinstance(ts, int):
            ts = int(time.time() * 1000)

        return VisionSample(
            faces=faces,
            gesture=gesture,
            timestamp_ms=ts,
            payload=payload,
        )

    @staticmethod
    def is_consistent(sample: VisionSample) -> bool:
        return sample.faces == sample.gesture

    def _dispatch(self, gesture_name: str) -> None:
        if self.dry_run:
            return

        player = self._ensure_player()
        player.play_gesture(
            gesture_name,
            hold_ms=self.hold_ms,
            enable=True,
            settle_s=0.6,
            relax_after_settle=True,
        )

    def on_match(self) -> tuple[str, str]:
        self._dispatch(self.match_gesture)
        return "on_match", self.match_gesture

    def on_mismatch(self) -> tuple[str, str]:
        self._dispatch(self.mismatch_gesture)
        return "on_mismatch", self.mismatch_gesture

    def check_and_act_once(self, timeout_s: float = 30.0) -> PipelineResult:
        sample = self.read_vision_sample(timeout_s=timeout_s)
        consistent = self.is_consistent(sample)
        if consistent:
            action_id, driver_gesture = self.on_match()
            reason = "faces.value == gesture.value"
            decision = "match"
        else:
            action_id, driver_gesture = self.on_mismatch()
            reason = "faces.value != gesture.value"
            decision = "mismatch"

        return PipelineResult(
            faces=sample.faces,
            gesture=sample.gesture,
            consistent=consistent,
            decision=decision,
            action_id=action_id,
            driver_gesture=driver_gesture,
            ok=True,
            reason=reason,
            timestamp_ms=sample.timestamp_ms,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check consistency between people count and hand gesture, then trigger hand action."
    )
    parser.add_argument("--mode", choices=["once", "loop"], default="once")
    parser.add_argument("--interval-ms", type=int, default=1200)
    parser.add_argument("--limit", type=int, default=0, help="0 means unlimited in loop mode")
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--hold-ms", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--match-gesture", default="correct")
    parser.add_argument("--mismatch-gesture", default="wrong")
    return parser.parse_args()


def result_to_json(result: PipelineResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=False)


def error_to_json(message: str) -> str:
    payload = {
        "faces": -1,
        "gesture": -1,
        "consistent": False,
        "decision": "unknown",
        "action_id": "none",
        "driver_gesture": "",
        "ok": False,
        "reason": message,
        "timestamp_ms": int(time.time() * 1000),
    }
    return json.dumps(payload, ensure_ascii=False)


def run_once(args: argparse.Namespace) -> int:
    with ConsistencyService(
        hold_ms=args.hold_ms,
        dry_run=args.dry_run,
        match_gesture=args.match_gesture,
        mismatch_gesture=args.mismatch_gesture,
    ) as service:
        result = service.check_and_act_once(timeout_s=args.timeout_s)
        print(result_to_json(result), flush=True)
    return 0


def run_loop(args: argparse.Namespace) -> int:
    count = 0
    with ConsistencyService(
        hold_ms=args.hold_ms,
        dry_run=args.dry_run,
        match_gesture=args.match_gesture,
        mismatch_gesture=args.mismatch_gesture,
    ) as service:
        while True:
            result = service.check_and_act_once(timeout_s=args.timeout_s)
            print(result_to_json(result), flush=True)
            count += 1
            if args.limit > 0 and count >= args.limit:
                break
            time.sleep(max(0.1, args.interval_ms / 1000.0))
    return 0


def main() -> int:
    args = parse_args()
    try:
        if args.mode == "once":
            return run_once(args)
        return run_loop(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(error_to_json(str(exc)), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
