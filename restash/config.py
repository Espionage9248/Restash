from __future__ import annotations
from dataclasses import dataclass, fields

# Maps restash.yml camelCase setting keys → Settings field names.
_PLUGIN_KEY_MAP = {
    "tasteHalfLifeDays": "taste_half_life_days",
    "cooldownDays": "cooldown_days",
    "freshWeight": "fresh_weight",
    "wildcardPercent": "wildcard_percent",
    "respectManualRatings": "respect_manual_ratings",
    "mirrorToRating100": "mirror_to_rating100",
    "excludeTagName": "exclude_tag_name",
    "dryRun": "dry_run",
}


@dataclass
class Settings:
    taste_half_life_days: float = 90.0
    cooldown_days: float = 21.0
    fresh_weight: float = 1.0
    wildcard_percent: float = 2.0
    respect_manual_ratings: bool = False
    mirror_to_rating100: bool = False
    exclude_tag_name: str = "[Restash: Exclude]"
    dry_run: bool = True
    # --- algorithm constants (spec §4 defaults), exposed for tuning ---
    o_event_value: float = 4.0
    play_event_value: float = 1.0
    abandonment_penalty: float = -0.5
    completion_floor: float = 0.25
    direct_scale: float = 6.0
    confidence_events: float = 5.0
    novelty_strength: float = 0.3
    novelty_half_life_days: float = 30.0
    rediscovery_max_days: float = 180.0
    just_watched_days: float = 2.0
    satiation_threshold: float = 0.25
    satiation_floor: float = 0.3
    satiation_window_days: float = 7.0
    jitter_amplitude: float = 0.06
    wildcard_low_conf_max_events: int = 1
    wildcard_band_low: float = 85.0
    wildcard_band_high: float = 95.0
    wildcard_pool_low: float = 0.40
    wildcard_pool_high: float = 0.70
    favorite_affinity_bonus: float = 0.5
    favorite_percentile_floor: float = 0.60
    ingredient_w_perf: float = 0.45
    ingredient_w_tag: float = 0.35
    ingredient_w_studio: float = 0.10
    ingredient_w_quality: float = 0.10
    perf_w_scenes: float = 0.40
    perf_w_affinity: float = 0.20
    perf_w_fresh: float = 0.15
    perf_w_supply: float = 0.15
    perf_w_novelty: float = 0.10
    # D11 (dry-run finding 2026-06-05): only treat a scene as "abandoned" when
    # completion is ALSO low. Stash resets resume_time to 0 on a finished scene,
    # so resume_time alone falsely penalized fully-watched scenes.
    abandonment_completion_max: float = 0.5
    # D12 (dry-run finding 2026-06-05): Bayesian-shrink the performer "best material"
    # term toward the population mean by evidence count (number of their scored
    # scenes), so a performer with a single strong scene (e.g. a whole ensemble cast
    # of one film) can't sit at the ceiling. Higher k = stronger pull toward the mean.
    perf_scenes_shrinkage_k: float = 3.0
    # D13 (sim finding 2026-06-05): the 90-day taste half-life was decaying a scene's
    # OWN evidence faster than the rediscovery curve could lift it, so beloved-but-
    # -dormant scenes faded instead of resurfacing. Give per-scene direct evidence a
    # slower half-life than the (taste-evolving) affinity model, and a stronger
    # rediscovery bonus, so old favourites genuinely climb back. Both tunable.
    direct_half_life_days: float = 365.0
    rediscovery_bonus: float = 0.40

    @classmethod
    def from_plugin_settings(cls, plugin_cfg: dict | None) -> "Settings":
        s = cls()
        if not plugin_cfg:
            return s
        bool_fields = {f.name for f in fields(cls) if f.type == "bool"}
        for plugin_key, field_name in _PLUGIN_KEY_MAP.items():
            if plugin_key not in plugin_cfg:
                continue
            value = plugin_cfg[plugin_key]
            if field_name in bool_fields:
                value = bool(value)
            elif field_name == "exclude_tag_name":
                value = str(value)
            else:
                value = float(value)
            setattr(s, field_name, value)
        return s
