#!/usr/bin/env python3
"""Dance service API smoke tests (no hardware required)."""

from __future__ import annotations

from pathlib import Path

from dance.api import DanceService
from dance.runtime import RuntimeState, RuntimeStatus


class FakeRuntime:
    """Fake runtime for API routing tests."""

    def __init__(self) -> None:
        self._status = RuntimeStatus(state=RuntimeState.IDLE, audio_enabled=True)

    def start(self, session_id, plan, track):
        _ = (plan,)
        self._status = RuntimeStatus(
            session_id=session_id,
            state=RuntimeState.RUNNING,
            track_id=track.track_id,
            track_path=track.path,
            bpm=track.bpm,
            beats_per_move=1,
            audio_enabled=True,
            audio_backend="fake",
            audio_state="playing",
        )
        return self._status

    def pause(self):
        self._status.state = RuntimeState.PAUSED
        self._status.audio_state = "paused"
        return self._status

    def resume(self):
        self._status.state = RuntimeState.RUNNING
        self._status.audio_state = "playing"
        return self._status

    def stop(self):
        self._status.state = RuntimeState.STOPPED
        self._status.audio_state = "stopped"
        return self._status

    def status(self):
        return self._status


def test_service_flow() -> None:
    root = Path(__file__).resolve().parent.parent
    svc = DanceService(
        catalog_path=str(root / "music" / "music_catalog.yaml"),
        gestures_path=str(root / "hand" / "demo_gestures.yaml"),
        runtime=FakeRuntime(),
    )

    res_start = svc.handle_action({"action": "dance.start", "prompt": "跟随音乐跳舞 10秒"})
    assert res_start["state"] == RuntimeState.RUNNING
    assert res_start["track_id"]
    assert Path(res_start["track_path"]).exists()

    res_pause = svc.handle_action({"action": "dance.pause"})
    assert res_pause["state"] == RuntimeState.PAUSED

    res_resume = svc.handle_action({"action": "dance.resume"})
    assert res_resume["state"] == RuntimeState.RUNNING

    res_stop = svc.handle_action({"action": "dance.stop"})
    assert res_stop["state"] == RuntimeState.STOPPED


def main() -> None:
    test_service_flow()
    print("dance service tests passed")


if __name__ == "__main__":
    main()
