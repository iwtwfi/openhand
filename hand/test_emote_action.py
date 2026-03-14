#!/usr/bin/env python3
"""Emote action tests (no hardware required)."""

from __future__ import annotations

from pathlib import Path
import tempfile

from run_emote_action import EmoteService


class FakePlayer:
    """Hardware-free fake player."""

    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.calls: list[str] = []

    def start(self) -> None:
        self.started = True

    def play_gesture(
        self,
        name: str,
        hold_ms: int | None = None,
        enable: bool | None = None,
        settle_s: float | None = None,
        relax_after_settle: bool = False,
    ) -> None:
        _ = (hold_ms, enable, settle_s, relax_after_settle)
        self.calls.append(name)

    def close(self) -> None:
        self.closed = True


def _build_service(tmp_dir: str, fake: FakePlayer, dance_state: str = "stopped") -> EmoteService:
    return EmoteService(
        player_factory=lambda: fake,
        sleep_fn=lambda _: None,
        dance_status_getter=lambda: {"state": dance_state},
        state_path=str(Path(tmp_dir) / "state.json"),
        lock_path=str(Path(tmp_dir) / "lock"),
    )


def test_social_reply_runs_greeting_preset() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake = FakePlayer()
        svc = _build_service(tmp_dir, fake=fake)
        result = svc.handle_action({"action": "social.reply", "text": "哈喽，在吗"})
        assert result["ok"] is True
        assert result["executed"] is True
        assert result["preset_id"] == "greet_wave_lr_v1"
        assert fake.started and fake.closed
        assert fake.calls == ["wave_left", "wave_right", "wave_left", "wave_right", "open_hand"]


def test_social_reply_not_matched() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake = FakePlayer()
        svc = _build_service(tmp_dir, fake=fake)
        result = svc.handle_action({"action": "social.reply", "text": "帮我播放音乐"})
        assert result["ok"] is True
        assert result["matched"] is False
        assert result["executed"] is False
        assert fake.calls == []


def test_social_reply_drops_when_dance_busy() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake = FakePlayer()
        svc = _build_service(tmp_dir, fake=fake, dance_state="running")
        result = svc.handle_action({"action": "social.reply", "text": "hello"})
        assert result["ok"] is True
        assert result["executed"] is False
        assert result["state"] == "busy"
        assert result["reason"] == "dance_active"
        assert fake.calls == []


def main() -> None:
    test_social_reply_runs_greeting_preset()
    test_social_reply_not_matched()
    test_social_reply_drops_when_dance_busy()
    print("emote action tests passed")


if __name__ == "__main__":
    main()
