#!/usr/bin/env python3
"""Dance choreography and beat-gating calculations."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Mapping, Any

from .intent import DanceIntent
from .music_selector import TrackInfo

try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit("missing dependency: pyyaml (pip install pyyaml)") from exc

_ALLOWED_BEATS_PER_MOVE = (1, 2, 4, 8)


@dataclass(frozen=True)
class DancePlan:
    """Frozen execution plan consumed by runtime."""

    style: str
    bpm: float
    beat_s: float
    settle_s: float
    guard_s: float
    beats_per_move: int
    move_interval_s: float
    hold_ms: int
    duration_s: float
    gesture_sequence: tuple[str, ...]


def _quantize_beats_per_move(raw: int) -> int:
    for candidate in _ALLOWED_BEATS_PER_MOVE:
        if raw <= candidate:
            return candidate
    return _ALLOWED_BEATS_PER_MOVE[-1]


def _load_available_gestures(path: str) -> set[str]:
    gesture_path = Path(path)
    if not gesture_path.exists():
        raise FileNotFoundError(f"gesture config not found: {gesture_path}")

    with gesture_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    gestures = data.get("gestures")
    if not isinstance(gestures, Mapping):
        raise ValueError("gesture config must contain a 'gestures' mapping")
    return {str(k) for k in gestures.keys()}


def _template_cycle(style: str) -> tuple[str, ...]:
    templates = {
        "energetic": ("open_hand", "fist", "peace", "rock", "open_hand", "half_fist"),
        "calm": ("open_hand", "half_fist", "digit_5", "half_fist"),
        "playful": ("open_hand", "digit_1", "digit_2", "thumbs_up", "peace"),
    }
    return templates.get(style, templates["energetic"])


def _fit_sequence(base_cycle: tuple[str, ...], moves: int) -> tuple[str, ...]:
    if moves <= 0:
        return tuple()
    out = []
    for i in range(moves):
        out.append(base_cycle[i % len(base_cycle)])
    return tuple(out)


def build_plan(
    intent: DanceIntent,
    track: TrackInfo,
    gestures_path: str,
    settle_s: float = 0.5,
    guard_s: float = 0.05,
) -> DancePlan:
    """Build a beat-gated choreography plan from intent + track."""
    bpm = max(1.0, float(track.bpm))
    beat_s = 60.0 / bpm

    stable_s = max(0.0, float(settle_s)) + max(0.0, float(guard_s))
    raw_k = int(ceil(stable_s / beat_s)) if beat_s > 0 else 1
    raw_k = max(1, raw_k)
    beats_per_move = _quantize_beats_per_move(raw_k)

    move_interval_s = beats_per_move * beat_s
    hold_ms = int(max(0.0, (move_interval_s - settle_s - guard_s) * 1000.0))

    moves = max(1, int(intent.duration_s / move_interval_s))

    available = _load_available_gestures(gestures_path)
    base = _template_cycle(intent.style)
    filtered = tuple(name for name in base if name in available)
    if not filtered:
        raise ValueError("no template gestures are available in demo_gestures.yaml")

    sequence = _fit_sequence(filtered, moves)

    return DancePlan(
        style=intent.style,
        bpm=bpm,
        beat_s=beat_s,
        settle_s=float(settle_s),
        guard_s=float(guard_s),
        beats_per_move=beats_per_move,
        move_interval_s=move_interval_s,
        hold_ms=hold_ms,
        duration_s=float(intent.duration_s),
        gesture_sequence=sequence,
    )
