from __future__ import annotations
import hashlib
import math
import statistics
from dataclasses import dataclass
from datetime import datetime

import models
from config import Settings


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * clamp(t, 0.0, 1.0)


def age_days(ts: datetime, now: datetime) -> float:
    return (now - ts).total_seconds() / 86400.0


def completion_factor(play_duration: float, play_count: int,
                      file_duration: float | None, floor: float) -> float:
    if not file_duration or file_duration <= 0 or play_count <= 0:
        return floor
    raw = play_duration / (play_count * file_duration)
    return clamp(raw, floor, 1.0)


def decay_weight(age_in_days: float, half_life: float) -> float:
    return 0.5 ** (age_in_days / half_life)


@dataclass
class Event:
    timestamp: datetime
    value: float
    kind: str   # "play" | "o" | "penalty"


def extract_events(scene: models.SceneData, cfg: Settings) -> list[Event]:
    events: list[Event] = []
    comp = completion_factor(scene.play_duration, scene.play_count,
                             scene.file_duration, cfg.completion_floor)
    for ts in scene.play_history:
        events.append(Event(ts, cfg.play_event_value * comp, "play"))
    for ts in scene.o_history:
        events.append(Event(ts, cfg.o_event_value, "o"))
    # Abandonment: last play resumed early and no o recorded after that play.
    if scene.play_history and scene.resume_time is not None and scene.file_duration:
        last_play = max(scene.play_history)
        resumed_early = scene.resume_time < 0.30 * scene.file_duration
        o_after = any(o > last_play for o in scene.o_history)
        if resumed_early and not o_after:
            events.append(Event(last_play, cfg.abandonment_penalty, "penalty"))
    return events


def decayed_event_sum(events: list[Event], now: datetime, half_life: float) -> float:
    return sum(e.value * decay_weight(age_days(e.timestamp, now), half_life)
               for e in events)


def n_events(events: list[Event]) -> int:
    return sum(1 for e in events if e.kind in ("play", "o"))


def freshness(d_days: float, cfg: Settings) -> float:
    """Cooldown→rediscovery curve, in [-0.9, +0.25]."""
    if d_days < cfg.just_watched_days:
        return -0.9
    if d_days < cfg.cooldown_days:
        return lerp(-0.9, 0.0,
                    (d_days - cfg.just_watched_days) /
                    (cfg.cooldown_days - cfg.just_watched_days))
    if d_days < cfg.rediscovery_max_days:
        return lerp(0.0, 0.25,
                    (d_days - cfg.cooldown_days) /
                    (cfg.rediscovery_max_days - cfg.cooldown_days))
    return 0.25


def novelty(library_age_days: float, cfg: Settings) -> float:
    return cfg.novelty_strength * (0.5 ** (library_age_days / cfg.novelty_half_life_days))


def daily_jitter(entity_id: str, date_seed: str, amplitude: float) -> float:
    digest = hashlib.sha256(f"{entity_id}:{date_seed}".encode()).digest()
    unit = int.from_bytes(digest[:8], "big") / 2 ** 64   # [0, 1)
    return unit * amplitude - amplitude / 2.0
