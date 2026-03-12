#!/usr/bin/env python3
"""Natural language intent parsing for dance control."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Any


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(秒|s|sec|seconds|分钟|min|mins)", re.IGNORECASE)


@dataclass(frozen=True)
class DanceIntent:
    """Parsed dance intent from prompt and overrides."""

    prompt: str
    style: str
    energy: float
    duration_s: float
    music_source: str


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _parse_duration_seconds(prompt: str) -> float | None:
    match = _DURATION_RE.search(prompt)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"分钟", "min", "mins"}:
        return value * 60.0
    return value


def _detect_style(prompt: str) -> str:
    lower = prompt.lower()
    mapping = {
        "energetic": ["活泼", "激情", "燃", "动感", "摇滚", "rock", "energetic"],
        "calm": ["舒缓", "慢", "平静", "温柔", "calm", "soft"],
        "playful": ["可爱", "俏皮", "fun", "playful"],
    }
    for style, keywords in mapping.items():
        if any(k in lower for k in keywords):
            return style
    return "energetic"


def _default_energy_for_style(style: str) -> float:
    defaults = {
        "energetic": 0.75,
        "calm": 0.45,
        "playful": 0.6,
    }
    return defaults.get(style, 0.65)


def parse_intent(prompt: str, overrides: Mapping[str, Any] | None = None) -> DanceIntent:
    """Parse user prompt + explicit fields into a normalized intent struct."""
    cfg = dict(overrides or {})

    style = str(cfg.get("style") or _detect_style(prompt)).strip().lower()

    raw_energy = cfg.get("energy")
    if raw_energy is None:
        energy = _default_energy_for_style(style)
    else:
        energy = _clip01(float(raw_energy))

    raw_duration = cfg.get("duration_s")
    if raw_duration is None:
        parsed = _parse_duration_seconds(prompt)
        duration_s = parsed if parsed is not None else 30.0
    else:
        duration_s = float(raw_duration)
    duration_s = max(5.0, min(600.0, duration_s))

    music = cfg.get("music")
    music_source = "auto"
    if isinstance(music, Mapping):
        music_source = str(music.get("source") or "auto").strip().lower()

    return DanceIntent(
        prompt=prompt,
        style=style,
        energy=energy,
        duration_s=duration_s,
        music_source=music_source,
    )
