#!/usr/bin/env python3
"""Track selection from a local music catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .intent import DanceIntent

try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit("missing dependency: pyyaml (pip install pyyaml)") from exc


@dataclass(frozen=True)
class TrackInfo:
    """Metadata required by choreography and runtime."""

    track_id: str
    path: str
    bpm: float
    style: str
    energy_min: float
    energy_max: float


def _as_float(item: Mapping[str, Any], key: str, default: float) -> float:
    value = item.get(key, default)
    return float(value)


def load_catalog(path: str) -> list[TrackInfo]:
    """Load local music catalog from YAML."""
    catalog_path = Path(path)
    if not catalog_path.exists():
        raise FileNotFoundError(f"music catalog not found: {catalog_path}")

    with catalog_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    tracks = data.get("tracks")
    if not isinstance(tracks, Sequence):
        raise ValueError("music catalog must contain a 'tracks' list")

    result: list[TrackInfo] = []
    for item in tracks:
        if not isinstance(item, Mapping):
            continue
        track = TrackInfo(
            track_id=str(item.get("track_id") or "").strip(),
            path=str(item.get("path") or "").strip(),
            bpm=_as_float(item, "bpm", 100.0),
            style=str(item.get("style") or "energetic").strip().lower(),
            energy_min=_as_float(item, "energy_min", 0.0),
            energy_max=_as_float(item, "energy_max", 1.0),
        )
        if not track.track_id or not track.path:
            continue
        if not Path(track.path).exists():
            continue
        result.append(track)

    if not result:
        raise ValueError("no valid tracks found in music catalog")
    return result


def _score_track(intent: DanceIntent, track: TrackInfo) -> float:
    style_score = 2.0 if track.style == intent.style else 0.0
    if intent.style in track.style or track.style in intent.style:
        style_score = max(style_score, 1.0)

    if track.energy_min <= intent.energy <= track.energy_max:
        energy_score = 2.0
    else:
        dist = min(abs(intent.energy - track.energy_min), abs(intent.energy - track.energy_max))
        energy_score = max(0.0, 2.0 - dist * 4.0)

    # Prefer moderate BPM when style/energy tie.
    bpm_center_penalty = abs(track.bpm - 105.0) / 100.0
    return style_score + energy_score - bpm_center_penalty


def select_track(
    intent: DanceIntent,
    catalog_path: str,
    preferred_track_id: str | None = None,
) -> TrackInfo:
    """Choose a track from catalog by style/energy, with optional explicit id."""
    tracks = load_catalog(catalog_path)

    if preferred_track_id:
        for track in tracks:
            if track.track_id == preferred_track_id:
                return track
        raise ValueError(f"preferred_track_id not found: {preferred_track_id}")

    ranked = sorted(tracks, key=lambda t: _score_track(intent, t), reverse=True)
    return ranked[0]
