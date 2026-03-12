#!/usr/bin/env python3
"""Top-level action API for dance control."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .choreo import build_plan
from .intent import parse_intent
from .music_selector import TrackInfo, select_track
from .runtime import DanceRuntime


class DanceService:
    """Action router for dance.start/pause/resume/stop/status."""

    def __init__(
        self,
        catalog_path: str | None = None,
        gestures_path: str | None = None,
        settle_s: float = 0.5,
        guard_s: float = 0.05,
        enable_audio: bool = True,
        runtime: DanceRuntime | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        self._catalog_path = str(catalog_path or (root / "music" / "music_catalog.yaml"))
        self._gestures_path = str(gestures_path or (root / "hand" / "demo_gestures.yaml"))
        self._settle_s = float(settle_s)
        self._guard_s = float(guard_s)
        self._runtime = runtime or DanceRuntime(enable_audio=enable_audio)

    def handle_action(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip().lower()
        if not action:
            raise ValueError("payload.action is required")

        if action in {"dance.start", "start"}:
            return self._handle_start(payload)
        if action in {"dance.pause", "pause"}:
            return self._status_response(self._runtime.pause())
        if action in {"dance.resume", "resume"}:
            return self._status_response(self._runtime.resume())
        if action in {"dance.stop", "stop"}:
            return self._status_response(self._runtime.stop())
        if action in {"dance.status", "status"}:
            return self._status_response(self._runtime.status())

        raise ValueError(f"unsupported action: {action}")

    def _handle_start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        prompt = str(payload.get("prompt") or "跟随音乐跳舞")
        overrides = {
            "style": payload.get("style"),
            "energy": payload.get("energy"),
            "duration_s": payload.get("duration_s"),
            "music": payload.get("music"),
        }
        intent = parse_intent(prompt, overrides=overrides)

        track = self._resolve_track(payload, intent.style, intent.energy)
        plan = build_plan(
            intent=intent,
            track=track,
            gestures_path=self._gestures_path,
            settle_s=self._settle_s,
            guard_s=self._guard_s,
        )

        session_id = f"sess_{uuid4().hex[:8]}"
        status = self._runtime.start(session_id=session_id, plan=plan, track=track)

        return {
            "session_id": session_id,
            "state": status.state,
            "track_id": track.track_id,
            "track_path": track.path,
            "bpm": track.bpm,
            "beats_per_move": plan.beats_per_move,
            "hold_ms": plan.hold_ms,
            "move_interval_s": plan.move_interval_s,
            "gesture_count": len(plan.gesture_sequence),
            "audio_enabled": status.audio_enabled,
            "audio_backend": status.audio_backend,
            "audio_state": status.audio_state,
            "warning": status.warning,
        }

    def _resolve_track(self, payload: Mapping[str, Any], style: str, energy: float) -> TrackInfo:
        music = payload.get("music")
        if isinstance(music, Mapping):
            source = str(music.get("source") or "auto").strip().lower()
            if source == "file":
                path = str(music.get("path") or "").strip()
                if not path:
                    raise ValueError("music.path is required when music.source=file")
                if not Path(path).exists():
                    raise FileNotFoundError(f"music file not found: {path}")
                bpm = float(music.get("bpm") or payload.get("bpm") or 100.0)
                return TrackInfo(
                    track_id=str(music.get("track_id") or Path(path).stem),
                    path=path,
                    bpm=bpm,
                    style=style,
                    energy_min=0.0,
                    energy_max=1.0,
                )

            preferred_track_id = music.get("track_id")
        else:
            preferred_track_id = payload.get("track_id")

        intent_like = parse_intent("", overrides={"style": style, "energy": energy, "duration_s": 30.0})
        return select_track(
            intent=intent_like,
            catalog_path=self._catalog_path,
            preferred_track_id=str(preferred_track_id) if preferred_track_id else None,
        )

    @staticmethod
    def _status_response(status_obj: Any) -> dict[str, Any]:
        return asdict(status_obj)
