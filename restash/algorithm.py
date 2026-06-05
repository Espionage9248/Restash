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


def satiation_multiplier(share: float, cfg: Settings) -> float:
    """D2: above threshold share, damp toward floor; ≤ threshold → 1.0."""
    if share <= cfg.satiation_threshold:
        return 1.0
    overexposure = clamp((share - cfg.satiation_threshold) /
                         (1.0 - cfg.satiation_threshold), 0.0, 1.0)
    return max(cfg.satiation_floor, 1.0 - overexposure)


def trailing_category_shares(scenes: list[models.SceneData], now: datetime,
                             cfg: Settings, attr: str) -> dict[str, float]:
    """Share of total (undecayed, positive) event value over the trailing window,
    per category id found in scene.<attr> (a list of ids)."""
    window = cfg.satiation_window_days
    per_cat: dict[str, float] = {}
    total = 0.0
    for scene in scenes:
        recent_value = sum(
            e.value for e in extract_events(scene, cfg)
            if e.kind in ("play", "o") and age_days(e.timestamp, now) <= window
        )
        if recent_value <= 0:
            continue
        total += recent_value
        for cat_id in getattr(scene, attr):
            per_cat[cat_id] = per_cat.get(cat_id, 0.0) + recent_value
    if total <= 0:
        return {}
    return {k: v / total for k, v in per_cat.items()}


def apply_satiation(affinities: dict[str, dict], scenes: list[models.SceneData],
                    now: datetime, cfg: Settings) -> dict[str, dict]:
    """D2: multiply each performer/tag affinity by its trailing-window satiation
    multiplier (mutates and returns `affinities`)."""
    for cls, attr in (("performers", "performer_ids"), ("tags", "tag_ids")):
        if cls not in affinities:
            continue
        shares = trailing_category_shares(scenes, now, cfg, attr)
        for key in affinities[cls]:
            affinities[cls][key] *= satiation_multiplier(shares.get(key, 0.0), cfg)
    return affinities


def _resolution_tier(height: int | None) -> float:
    if not height:
        return 0.3
    if height < 480:
        return 0.3
    if height < 720:
        return 0.5
    if height < 1080:
        return 0.7
    if height < 2160:
        return 0.9
    return 1.0


def quality_prior(scene: models.SceneData, dur_median: float | None,
                  dur_scale: float | None, cfg: Settings) -> float:
    """[0,1] blend: resolution, duration sweet-spot, marker density, organized."""
    res = _resolution_tier(scene.height)
    if dur_median and dur_scale and scene.file_duration:
        z = (scene.file_duration - dur_median) / dur_scale
        dur = math.exp(-0.5 * z * z)
    else:
        dur = 0.5
    markers = clamp(scene.marker_count / 10.0, 0.0, 1.0)
    organized = 1.0 if scene.organized else 0.0
    return clamp(0.4 * res + 0.3 * dur + 0.2 * markers + 0.1 * organized, 0.0, 1.0)


def duration_sweet_spot(scenes: list[models.SceneData]) -> tuple[float | None, float | None]:
    """Median ± MAD of file_duration over scenes with ≥1 o (spec §4.3)."""
    durs = [s.file_duration for s in scenes
            if s.o_counter > 0 and s.file_duration and s.file_duration > 0]
    if len(durs) < 3:
        return None, None
    median = statistics.median(durs)
    mad = statistics.median([abs(d - median) for d in durs])
    scale = mad * 1.4826 + 1e-9   # MAD→σ-equivalent, avoid /0
    return median, scale


def build_affinities(scenes: list[models.SceneData], now: datetime, cfg: Settings,
                     favorites: set[str], ratings: dict[str, int]) -> dict[str, dict]:
    """Returns {'performers':{id:aff}, 'tags':{...}, 'studios':{...}}, each in [-1,1],
    with satiation (D2) already applied to performers and tags."""
    classes = {"performers": ("performer_ids", True), "tags": ("tag_ids", True),
               "studios": ("studio_id", False)}
    value_sums = {c: {} for c in classes}
    exposure = {c: {} for c in classes}

    for scene in scenes:
        dsum = decayed_event_sum(extract_events(scene, cfg), now,
                                 cfg.taste_half_life_days)
        for cls, (attr, is_list) in classes.items():
            ids = getattr(scene, attr)
            ids = ids if is_list else ([ids] if ids else [])
            for key in ids:
                value_sums[cls][key] = value_sums[cls].get(key, 0.0) + dsum
                exposure[cls][key] = exposure[cls].get(key, 0) + 1

    result: dict[str, dict] = {}
    for cls in classes:
        zscores = _zscores(affinity_raw(value_sums[cls], exposure[cls]))
        if cls == "performers":
            result[cls] = apply_performer_priors(zscores, favorites, ratings, cfg)
        else:
            result[cls] = {k: math.tanh(z) for k, z in zscores.items()}

    return apply_satiation(result, scenes, now, cfg)   # D2, performers + tags


def _mean_top_n(values: list[float], n: int) -> float:
    if not values:
        return 0.0
    top = sorted(values, reverse=True)[:n]
    return sum(top) / len(top)


def scene_base(scene: models.SceneData, aff: dict[str, dict],
               tag_scene_counts: dict[str, int], dur_median: float | None,
               dur_scale: float | None, cfg: Settings, now: datetime) -> dict:
    """Returns a components dict including 'ingredients', 'direct', 'confidence',
    'base' and the sub-parts, all on the [-1,1] scale (quality centered, D1)."""
    perf_affs = [aff["performers"].get(p, 0.0) for p in scene.performer_ids]
    perf_term = _mean_top_n(perf_affs, 3)

    if scene.tag_ids:
        num = den = 0.0
        for t in scene.tag_ids:
            w = 1.0 / math.log2(2 + tag_scene_counts.get(t, 1))
            num += w * aff["tags"].get(t, 0.0)
            den += w
        tag_term = num / den if den else 0.0
    else:
        tag_term = 0.0

    studio_term = aff["studios"].get(scene.studio_id, 0.0) if scene.studio_id else 0.0
    quality01 = quality_prior(scene, dur_median, dur_scale, cfg)
    quality_term = 2.0 * quality01 - 1.0   # center to [-1,1] (D1 consistency)

    ingredients = (cfg.ingredient_w_perf * perf_term
                   + cfg.ingredient_w_tag * tag_term
                   + cfg.ingredient_w_studio * studio_term
                   + cfg.ingredient_w_quality * quality_term)

    events = extract_events(scene, cfg)
    ne = n_events(events)
    dsum = decayed_event_sum(events, now, cfg.taste_half_life_days)
    direct = math.tanh(dsum / cfg.direct_scale)
    confidence = min(1.0, ne / cfg.confidence_events)
    base = confidence * direct + (1.0 - confidence) * ingredients

    return {"perf": perf_term, "tag": tag_term, "studio": studio_term,
            "quality": quality_term, "ingredients": ingredients, "direct": direct,
            "confidence": confidence, "base": base, "n_events": ne}


def score_scenes(scenes: list[models.SceneData], cfg: Settings, now: datetime,
                 date_seed: str, favorites: set[str] | None = None,
                 ratings: dict[str, int] | None = None,
                 aff: dict[str, dict] | None = None) -> dict[str, models.SceneScore]:
    favorites = favorites or set()
    ratings = ratings or {}
    if aff is None:
        aff = build_affinities(scenes, now, cfg, favorites, ratings)
    tag_counts: dict[str, int] = {}
    for s in scenes:
        for t in s.tag_ids:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    dur_median, dur_scale = duration_sweet_spot(scenes)

    pre: dict[str, dict] = {}
    raw_values: list[float] = []
    ids: list[str] = []
    for s in scenes:
        comp = scene_base(s, aff, tag_counts, dur_median, dur_scale, cfg, now)
        ne = comp["n_events"]
        if ne == 0:
            lib_age = age_days(s.created_at, now)
            nov = novelty(lib_age, cfg)
            final = comp["base"] + nov
            comp["fresh"] = 0.0
            comp["fresh_d"] = None
            comp["novelty"] = nov
        else:
            last = _last_engagement(s)
            d = age_days(last, now) if last else cfg.rediscovery_max_days
            f = freshness(d, cfg)
            final = comp["base"] + f * abs(comp["base"]) * cfg.fresh_weight
            comp["fresh"] = f
            comp["fresh_d"] = d
            comp["novelty"] = 0.0
        jit = daily_jitter(s.id, date_seed, cfg.jitter_amplitude)
        comp["jitter"] = jit
        final += jit
        comp["raw"] = final
        pre[s.id] = comp
        raw_values.append(final)
        ids.append(s.id)

    pcts = percentiles(raw_values)
    scores: dict[str, models.SceneScore] = {}
    for idx, sid in enumerate(ids):
        comp = pre[sid]
        scores[sid] = models.SceneScore(
            id=sid, raw=comp["raw"], restash_score=to_restash_score(pcts[idx]),
            percentile=pcts[idx], n_events=comp["n_events"], wildcard=False,
            components=comp)
    _apply_wildcards(scores, cfg, date_seed)
    return scores


def _last_engagement(scene: models.SceneData) -> datetime | None:
    candidates = []
    if scene.play_history:
        candidates.append(max(scene.play_history))
    if scene.last_played_at:
        candidates.append(scene.last_played_at)
    if scene.o_history:
        candidates.append(max(scene.o_history))
    return max(candidates) if candidates else None


def _apply_wildcards(scores: dict[str, models.SceneScore], cfg: Settings,
                     date_seed: str) -> None:
    """D4: date-seeded override of a few low-confidence mid-pack scenes into 85–95.
    Only the chosen scenes change; everyone else keeps their percentile rank."""
    lo_b, hi_b = cfg.wildcard_band_low, cfg.wildcard_band_high
    lo_p, hi_p = cfg.wildcard_pool_low, cfg.wildcard_pool_high
    pool = [s for s in scores.values()
            if lo_p <= s.percentile <= hi_p
            and s.n_events <= cfg.wildcard_low_conf_max_events]
    if not pool:
        return
    target = int(len(scores) * cfg.wildcard_percent / 100.0)
    target = min(target, len(pool))
    if target <= 0:
        return
    pool.sort(key=lambda s: daily_jitter(s.id, date_seed + ":wild", 1.0))
    for s in pool[:target]:
        spread = (daily_jitter(s.id, date_seed + ":band", 1.0) + 0.5)  # [0,1)
        s.restash_score = int(round(lo_b + spread * (hi_b - lo_b)))
        s.wildcard = True
        s.components["wildcard"] = 1.0
