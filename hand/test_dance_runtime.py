#!/usr/bin/env python3
"""Dance runtime smoke tests (no hardware required)."""

from __future__ import annotations

from pathlib import Path
import time

from dance.choreo import build_plan
from dance.intent import DanceIntent
from dance.music_selector import TrackInfo
from dance.runtime import DanceRuntime, RuntimeState


class FakePlayer:
    """Hardware-free fake player used by tests."""

    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.calls: list[str] = []
        self.relax_flags: list[bool] = []

    def start(self) -> None:
        self.started = True

    def play_gesture(
        self,
        name: str,
        hold_ms: int | None = None,
        enable: bool | None = None,
        settle_s: float | None = None,
        relax_after_settle: bool = True,
    ) -> None:
        _ = (hold_ms, enable, settle_s, relax_after_settle)
        self.calls.append(name)
        self.relax_flags.append(bool(relax_after_settle))

    def close(self) -> None:
        self.closed = True


class FakeAudio:
    """Audio backend fake with pause/resume/stop state."""

    def __init__(self) -> None:
        self.backend_name = "fake"
        self.state = "stopped"
        self.started_path = ""

    def start(self, path: str) -> None:
        self.started_path = path
        self.state = "playing"

    def pause(self) -> None:
        self.state = "paused"

    def resume(self) -> None:
        self.state = "playing"

    def stop(self) -> None:
        self.state = "stopped"


def _wait_until_stopped(runtime: DanceRuntime, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = runtime.status()
        if status.state in {RuntimeState.STOPPED, RuntimeState.ERROR}:
            return
        time.sleep(0.05)
    raise TimeoutError("runtime did not stop in time")


def test_plan_quantization() -> None:
    intent = DanceIntent(
        prompt="测试",
        style="energetic",
        energy=0.7,
        duration_s=6.0,
        music_source="auto",
    )
    track = TrackInfo(
        track_id="t1",
        path="/home/xu/openhand/music/generated_dance_100bpm_45s.wav",
        bpm=140.0,
        style="energetic",
        energy_min=0.0,
        energy_max=1.0,
    )

    plan = build_plan(
        intent=intent,
        track=track,
        gestures_path=str(Path(__file__).with_name("demo_gestures.yaml")),
        settle_s=0.5,
        guard_s=0.05,
    )
    assert plan.beats_per_move == 2
    assert plan.hold_ms >= 0
    assert len(plan.gesture_sequence) > 0


def test_runtime_smoke() -> None:
    fake = FakePlayer()
    fake_audio = FakeAudio()
    runtime = DanceRuntime(
        player_factory=lambda: fake,
        audio_player_factory=lambda: fake_audio,
        enable_audio=True,
    )

    intent = DanceIntent(
        prompt="测试",
        style="energetic",
        energy=0.7,
        duration_s=2.0,
        music_source="auto",
    )
    track = TrackInfo(
        track_id="t2",
        path="/home/xu/openhand/music/generated_dance_100bpm_45s.wav",
        bpm=100.0,
        style="energetic",
        energy_min=0.0,
        energy_max=1.0,
    )
    plan = build_plan(
        intent=intent,
        track=track,
        gestures_path=str(Path(__file__).with_name("demo_gestures.yaml")),
        settle_s=0.0,
        guard_s=0.0,
    )

    runtime.start(session_id="sess_test", plan=plan, track=track)
    _wait_until_stopped(runtime, timeout_s=4.0)

    status = runtime.status()
    assert status.state == RuntimeState.STOPPED
    assert fake.started
    assert fake.closed
    assert len(fake.calls) == len(plan.gesture_sequence)
    assert all(fake.relax_flags)
    assert fake_audio.started_path == track.path


def main() -> None:
    test_plan_quantization()
    test_runtime_smoke()
    print("dance runtime tests passed")


if __name__ == "__main__":
    main()
