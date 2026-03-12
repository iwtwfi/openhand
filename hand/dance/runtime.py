#!/usr/bin/env python3
"""Threaded runtime for executing dance plans on DemoGesturePlayer."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable

from .audio_player import BackgroundAudioPlayer
from .choreo import DancePlan
from .music_selector import TrackInfo

try:
    from demo_gesture_player import DemoGesturePlayer
except ModuleNotFoundError:
    hand_root = Path(__file__).resolve().parent.parent
    if str(hand_root) not in sys.path:
        sys.path.insert(0, str(hand_root))
    from demo_gesture_player import DemoGesturePlayer


class RuntimeState:
    """String constants for runtime state."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class RuntimeStatus:
    """Current runtime status snapshot."""

    session_id: str = ""
    state: str = RuntimeState.IDLE
    track_id: str = ""
    track_path: str = ""
    bpm: float = 0.0
    beats_per_move: int = 0
    current_gesture: str = ""
    move_index: int = 0
    beat_index: int = 0
    started_at_monotonic: float = 0.0
    audio_enabled: bool = False
    audio_backend: str = "none"
    audio_state: str = "stopped"
    warning: str = ""
    error: str = ""


class DanceRuntime:
    """Single-session dance runtime.

    Notes:
    1. Keep one active session because hardware is single hand device.
    2. Preserve blocking play_gesture() semantics for motion stability.
    """

    def __init__(
        self,
        player_factory: Callable[[], Any] | None = None,
        audio_player_factory: Callable[[], Any] | None = None,
        enable_audio: bool = True,
    ) -> None:
        self._player_factory = player_factory or DemoGesturePlayer
        self._audio_player_factory = audio_player_factory or BackgroundAudioPlayer
        self._enable_audio = bool(enable_audio)

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._audio: Any | None = None
        self._status = RuntimeStatus(audio_enabled=self._enable_audio)

    def start(self, session_id: str, plan: DancePlan, track: TrackInfo) -> RuntimeStatus:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("runtime already has an active session")
            self._stop_event.clear()
            self._pause_event.clear()
            self._status = RuntimeStatus(
                session_id=session_id,
                state=RuntimeState.STARTING,
                track_id=track.track_id,
                track_path=track.path,
                bpm=plan.bpm,
                beats_per_move=plan.beats_per_move,
                audio_enabled=self._enable_audio,
            )
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(plan, track),
                name=f"dance-runtime-{session_id}",
                daemon=True,
            )
            self._thread.start()
            return RuntimeStatus(**asdict(self._status))

    def pause(self) -> RuntimeStatus:
        with self._lock:
            if self._status.state != RuntimeState.RUNNING:
                return RuntimeStatus(**asdict(self._status))
            self._pause_event.set()
            self._status.state = RuntimeState.PAUSED
            audio = self._audio

        if audio is not None:
            try:
                audio.pause()
                with self._lock:
                    self._status.audio_state = str(getattr(audio, "state", "paused"))
            except Exception as exc:
                with self._lock:
                    self._status.warning = f"audio pause failed: {exc}"

        with self._lock:
            return RuntimeStatus(**asdict(self._status))

    def resume(self) -> RuntimeStatus:
        with self._lock:
            if self._status.state != RuntimeState.PAUSED:
                return RuntimeStatus(**asdict(self._status))
            self._pause_event.clear()
            self._status.state = RuntimeState.RUNNING
            audio = self._audio

        if audio is not None:
            try:
                audio.resume()
                with self._lock:
                    self._status.audio_state = str(getattr(audio, "state", "playing"))
            except Exception as exc:
                with self._lock:
                    self._status.warning = f"audio resume failed: {exc}"

        with self._lock:
            return RuntimeStatus(**asdict(self._status))

    def stop(self, timeout_s: float = 3.0) -> RuntimeStatus:
        thread: threading.Thread | None
        audio: Any | None
        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                self._status.state = RuntimeState.STOPPED
                return RuntimeStatus(**asdict(self._status))
            self._status.state = RuntimeState.STOPPING
            self._stop_event.set()
            self._pause_event.clear()
            audio = self._audio

        if audio is not None:
            try:
                audio.stop()
                with self._lock:
                    self._status.audio_state = str(getattr(audio, "state", "stopped"))
            except Exception as exc:
                with self._lock:
                    self._status.warning = f"audio stop failed: {exc}"

        if thread:
            thread.join(timeout=max(0.1, timeout_s))

        with self._lock:
            if self._thread and self._thread.is_alive():
                self._status.error = "stop timeout"
                self._status.state = RuntimeState.ERROR
            else:
                self._status.state = RuntimeState.STOPPED
            return RuntimeStatus(**asdict(self._status))

    def status(self) -> RuntimeStatus:
        with self._lock:
            return RuntimeStatus(**asdict(self._status))

    def _run_loop(self, plan: DancePlan, track: TrackInfo) -> None:
        player = self._player_factory()
        start_mono = time.monotonic()

        try:
            if self._enable_audio:
                self._start_audio(track.path)

            player.start()
            with self._lock:
                self._status.state = RuntimeState.RUNNING
                self._status.started_at_monotonic = start_mono

            next_deadline = start_mono
            beat_index = 0

            for move_index, gesture in enumerate(plan.gesture_sequence, start=1):
                if self._stop_event.is_set():
                    break

                while self._pause_event.is_set() and not self._stop_event.is_set():
                    time.sleep(0.05)

                if self._stop_event.is_set():
                    break

                with self._lock:
                    self._status.current_gesture = gesture
                    self._status.move_index = move_index
                    self._status.beat_index = beat_index

                player.play_gesture(
                    gesture,
                    hold_ms=plan.hold_ms,
                    enable=True,
                    settle_s=plan.settle_s,
                    relax_after_settle=True,
                )

                beat_index += plan.beats_per_move
                next_deadline += plan.move_interval_s

                lag = time.monotonic() - next_deadline
                if lag < -0.002:
                    time.sleep(-lag)
                elif lag > plan.move_interval_s:
                    next_deadline = time.monotonic()

            with self._lock:
                if self._status.state != RuntimeState.ERROR:
                    self._status.state = RuntimeState.STOPPED

        except Exception as exc:  # pragma: no cover - hardware path
            with self._lock:
                self._status.state = RuntimeState.ERROR
                self._status.error = str(exc)
        finally:
            try:
                player.close()
            except Exception as close_exc:  # pragma: no cover - hardware path
                with self._lock:
                    if not self._status.error:
                        self._status.error = f"close failed: {close_exc}"
                        self._status.state = RuntimeState.ERROR

            self._finalize_audio()

            self._stop_event.clear()
            self._pause_event.clear()
            with self._lock:
                self._thread = None

    def _start_audio(self, track_path: str) -> None:
        audio = self._audio_player_factory()
        with self._lock:
            self._audio = audio

        try:
            audio.start(track_path)
            with self._lock:
                self._status.audio_backend = str(getattr(audio, "backend_name", "unknown"))
                self._status.audio_state = str(getattr(audio, "state", "playing"))
        except Exception as exc:
            with self._lock:
                self._status.warning = f"audio disabled: {exc}"
                self._status.audio_state = "error"

    def _finalize_audio(self) -> None:
        with self._lock:
            audio = self._audio
            self._audio = None

        if audio is None:
            return

        try:
            audio.stop()
        except Exception as exc:
            with self._lock:
                if not self._status.warning:
                    self._status.warning = f"audio finalize failed: {exc}"
        finally:
            with self._lock:
                self._status.audio_state = "stopped"

    @staticmethod
    def status_to_dict(status: RuntimeStatus) -> dict[str, Any]:
        return asdict(status)
