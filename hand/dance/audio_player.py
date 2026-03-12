#!/usr/bin/env python3
"""Background audio playback utility for local files."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import signal
import subprocess
from typing import Sequence


@dataclass(frozen=True)
class AudioBackend:
    """Executable command template for one audio backend."""

    name: str
    argv_prefix: tuple[str, ...]


class BackgroundAudioPlayer:
    """Best-effort local audio player using system commands."""

    _BACKENDS: tuple[AudioBackend, ...] = (
        AudioBackend(name="ffplay", argv_prefix=("ffplay", "-nodisp", "-autoexit", "-loglevel", "error")),
        AudioBackend(name="mpg123", argv_prefix=("mpg123", "-q")),
        AudioBackend(name="aplay", argv_prefix=("aplay", "-q")),
    )

    def __init__(self, backends: Sequence[AudioBackend] | None = None) -> None:
        self._backends = tuple(backends or self._BACKENDS)
        self._proc: subprocess.Popen[bytes] | None = None
        self._backend_name = "none"
        self._state = "stopped"

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def state(self) -> str:
        return self._state

    def start(self, file_path: str) -> None:
        """Start audio playback for a local file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"audio file not found: {path}")

        self.stop()
        backend = self._pick_backend()
        if backend is None:
            raise RuntimeError("no audio backend found (ffplay/mpg123/aplay)")

        argv = [*backend.argv_prefix, str(path)]
        self._proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        self._backend_name = backend.name
        self._state = "playing"

    def pause(self) -> None:
        """Pause playback if currently running."""
        proc = self._proc
        if not proc or proc.poll() is not None:
            self._state = "stopped"
            return

        os.killpg(os.getpgid(proc.pid), signal.SIGSTOP)
        self._state = "paused"

    def resume(self) -> None:
        """Resume paused playback."""
        proc = self._proc
        if not proc or proc.poll() is not None:
            self._state = "stopped"
            return

        os.killpg(os.getpgid(proc.pid), signal.SIGCONT)
        self._state = "playing"

    def stop(self, timeout_s: float = 1.5) -> None:
        """Stop playback and clear process state."""
        proc = self._proc
        if not proc:
            self._state = "stopped"
            return

        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=max(0.1, timeout_s))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=0.5)

        self._proc = None
        self._state = "stopped"

    def _pick_backend(self) -> AudioBackend | None:
        for backend in self._backends:
            exe = backend.argv_prefix[0]
            if shutil.which(exe):
                return backend
        return None
