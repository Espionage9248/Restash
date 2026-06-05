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


def percentiles(values: list[float]) -> list[float]:
    """Average-rank percentile in [0,1]; tied values share their mean rank (D3)."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    # round to absorb float noise so genuine ties group together
    keyed = [(round(v, 9), i) for i, v in enumerate(values)]
    order = sorted(range(n), key=lambda i: keyed[i][0])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and keyed[order[j + 1]][0] == keyed[order[i]][0]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return [r / (n - 1) for r in ranks]


def to_restash_score(percentile: float) -> int:
    return max(1, round(100 * percentile))


def affinity_raw(value_sums: dict[str, float],
                 exposure_counts: dict[str, int]) -> dict[str, float]:
    """Σ decayed event values / log2(2 + count_of_scenes_with_x) (spec §4.2)."""
    out = {}
    for key, total in value_sums.items():
        count = exposure_counts.get(key, 0)
        out[key] = total / math.log2(2 + count)
    return out


def _zscores(raw: dict[str, float]) -> dict[str, float]:
    """Z-score each value across the class; zero variance → all 0.0 (D10 guard).
    Returns PRE-tanh z-scores so callers can add priors before squashing."""
    if not raw:
        return {}
    vals = list(raw.values())
    mean = statistics.fmean(vals)
    stdev = statistics.pstdev(vals)
    if stdev < 1e-12:
        return {k: 0.0 for k in raw}
    return {k: (v - mean) / stdev for k, v in raw.items()}


def normalize_affinities(raw: dict[str, float]) -> dict[str, float]:
    """Z-score across the class, squash with tanh → [-1, 1] (tags/studios path)."""
    return {k: math.tanh(z) for k, z in _zscores(raw).items()}


def apply_performer_priors(zscored: dict[str, float], favorites: set[str],
                           ratings: dict[str, int], cfg: Settings) -> dict[str, float]:
    """Take PRE-tanh z-scores, add favorite bonus + manual-rating blend, then squash
    once with tanh. Used for the performer class (priors must precede the squash)."""
    out = {}
    for key, z in zscored.items():
        adjusted = z
        if key in favorites:
            adjusted += cfg.favorite_affinity_bonus
        if key in ratings and ratings[key] is not None:
            adjusted += (ratings[key] - 50) / 50.0 * 0.5
        out[key] = math.tanh(adjusted)
    return out
