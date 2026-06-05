import math
from datetime import datetime, timedelta, timezone
import algorithm as alg
import models
from config import Settings

NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)

def days_ago(n):  # helper
    return NOW - timedelta(days=n)

def test_clamp_and_lerp():
    assert alg.clamp(5, 0, 1) == 1
    assert alg.clamp(-2, 0, 1) == 0
    assert alg.lerp(0, 10, 0.5) == 5
    assert alg.lerp(0, 10, 2) == 10   # t clamped

def test_completion_factor_floor_and_cap():
    # no file duration → floor
    assert alg.completion_factor(100, 2, None, 0.25) == 0.25
    # full completion capped at 1.0
    assert alg.completion_factor(1000, 1, 100, 0.25) == 1.0
    # half watched
    assert alg.completion_factor(50, 1, 100, 0.25) == 0.5
    # tiny sample floored
    assert alg.completion_factor(1, 1, 100, 0.25) == 0.25

def test_decay_weight_halves_each_half_life():
    assert alg.decay_weight(0, 90) == 1.0
    assert alg.decay_weight(90, 90) == 0.5
    assert math.isclose(alg.decay_weight(180, 90), 0.25)

def _scene(**kw):
    base = dict(id="s", title="t", play_history=[], o_history=[], play_count=0,
        o_counter=0, play_duration=0.0, resume_time=None, last_played_at=None,
        file_duration=100.0, height=1080, marker_count=0, organized=False,
        date=None, created_at=days_ago(400), rating100=None, tag_ids=[],
        performer_ids=[], studio_id=None, custom_fields={}, has_file=True)
    base.update(kw)
    return models.SceneData(**base)

def test_extract_events_play_and_o_values():
    s = _scene(play_history=[days_ago(0)], o_history=[days_ago(0)],
               play_count=1, o_counter=1, play_duration=100.0)
    ev = alg.extract_events(s, Settings())
    kinds = sorted(e.kind for e in ev)
    assert kinds == ["o", "play"]
    o_event = next(e for e in ev if e.kind == "o")
    play_event = next(e for e in ev if e.kind == "play")
    assert o_event.value == 4.0
    assert play_event.value == 1.0   # full completion

def test_abandonment_penalty_when_resumed_early_and_no_o_after():
    s = _scene(play_history=[days_ago(1)], play_count=1, play_duration=10.0,
               resume_time=5.0, file_duration=100.0)  # 5% in, no o
    ev = alg.extract_events(s, Settings())
    assert any(e.kind == "penalty" and e.value == -0.5 for e in ev)

def test_no_abandonment_penalty_if_o_after_play():
    s = _scene(play_history=[days_ago(2)], o_history=[days_ago(1)], play_count=1,
               o_counter=1, play_duration=10.0, resume_time=5.0, file_duration=100.0)
    ev = alg.extract_events(s, Settings())
    assert not any(e.kind == "penalty" for e in ev)

def test_decayed_event_sum_decays_old_events():
    recent = _scene(o_history=[days_ago(0)], o_counter=1)
    old = _scene(o_history=[days_ago(90)], o_counter=1)
    s_recent = alg.decayed_event_sum(alg.extract_events(recent, Settings()), NOW, 90)
    s_old = alg.decayed_event_sum(alg.extract_events(old, Settings()), NOW, 90)
    assert math.isclose(s_recent, 4.0)
    assert math.isclose(s_old, 2.0)   # one 90-day half-life

def test_n_events_counts_play_and_o_only():
    s = _scene(play_history=[days_ago(1)], o_history=[days_ago(1)], play_count=1,
               o_counter=1, play_duration=10.0, resume_time=1.0, file_duration=100.0)
    ev = alg.extract_events(s, Settings())
    assert alg.n_events(ev) == 2   # penalty not counted

def test_freshness_curve_shape():
    cfg = Settings()
    assert alg.freshness(0, cfg) == -0.9          # just watched: buried
    assert alg.freshness(1.9, cfg) == -0.9
    assert math.isclose(alg.freshness(21, cfg), 0.0, abs_tol=1e-9)   # cooldown end
    assert alg.freshness(11.5, cfg) < 0           # mid-cooldown still negative
    assert alg.freshness(180, cfg) == 0.25        # full rediscovery
    assert alg.freshness(5000, cfg) == 0.25       # capped
    assert 0 < alg.freshness(100, cfg) < 0.25     # rediscovery ramp

def test_freshness_is_monotonic_nondecreasing_after_2_days():
    cfg = Settings()
    xs = [alg.freshness(d, cfg) for d in range(2, 400)]
    assert all(b >= a - 1e-12 for a, b in zip(xs, xs[1:]))

def test_novelty_decays_by_half_every_30_days():
    cfg = Settings()
    assert math.isclose(alg.novelty(0, cfg), 0.3)
    assert math.isclose(alg.novelty(30, cfg), 0.15)
    assert math.isclose(alg.novelty(60, cfg), 0.075)

def test_daily_jitter_is_deterministic_and_bounded():
    a = alg.daily_jitter("scene-1", "2026-06-05", 0.06)
    b = alg.daily_jitter("scene-1", "2026-06-05", 0.06)
    c = alg.daily_jitter("scene-1", "2026-06-06", 0.06)
    assert a == b              # same id+date → identical
    assert a != c              # next day differs
    assert -0.03 <= a <= 0.03  # ±amplitude/2

def test_daily_jitter_differs_across_ids():
    a = alg.daily_jitter("scene-1", "2026-06-05", 0.06)
    b = alg.daily_jitter("scene-2", "2026-06-05", 0.06)
    assert a != b

def test_percentiles_spread_min_to_max():
    pcts = alg.percentiles([10.0, 20.0, 30.0])
    assert pcts == [0.0, 0.5, 1.0]

def test_percentiles_average_rank_for_ties():
    # two tied at the top share the average of ranks 1 and 2 (0-based)
    pcts = alg.percentiles([5.0, 9.0, 9.0])
    assert pcts[0] == 0.0
    assert pcts[1] == pcts[2] == ((1 + 2) / 2) / 2  # avg 0-based rank 1.5 / (n-1=2)

def test_percentiles_single_and_empty():
    assert alg.percentiles([]) == []
    assert alg.percentiles([42.0]) == [1.0]

def test_to_restash_score_floor_and_round():
    assert alg.to_restash_score(0.0) == 1     # floored at 1
    assert alg.to_restash_score(1.0) == 100
    assert alg.to_restash_score(0.874) == 87

def test_affinity_exposure_normalization_favors_rarer():
    # tag A appears on 2 scenes, tag B on 8; equal total decayed value per appearance.
    # exposure denom log2(2+count) penalizes the common tag's raw affinity.
    raw = alg.affinity_raw({"A": 8.0, "B": 8.0}, {"A": 2, "B": 8})
    assert raw["A"] > raw["B"]

def test_zscore_tanh_normalizes_and_squashes_into_unit_range():
    out = alg.normalize_affinities({"A": 10.0, "B": 0.0, "C": -10.0})
    assert all(-1.0 <= v <= 1.0 for v in out.values())
    assert out["A"] > out["B"] > out["C"]

def test_zscore_zero_variance_falls_back_to_neutral():
    out = alg.normalize_affinities({"A": 5.0, "B": 5.0, "C": 5.0})
    assert out == {"A": 0.0, "B": 0.0, "C": 0.0}

def test_performer_favorite_bonus_and_rating_blend():
    base = {"p1": 0.0}
    fav = alg.apply_performer_priors(dict(base), favorites={"p1"}, ratings={},
                                     cfg=Settings())
    assert fav["p1"] > 0   # +0.5 then tanh
    rated = alg.apply_performer_priors({"p2": 0.0}, favorites=set(),
                                       ratings={"p2": 100}, cfg=Settings())
    assert rated["p2"] > 0   # (100-50)/50*0.5 = +0.5 then tanh

def test_satiation_multiplier_thresholds():
    cfg = Settings()
    assert alg.satiation_multiplier(0.10, cfg) == 1.0     # below 25% → no damping
    assert alg.satiation_multiplier(0.25, cfg) == 1.0     # exactly at threshold
    assert math.isclose(alg.satiation_multiplier(0.625, cfg), 0.5)  # halfway → 0.5
    assert alg.satiation_multiplier(1.0, cfg) == 0.3      # total binge floored at 0.3

def test_trailing_shares_sum_to_one_over_window():
    cfg = Settings()
    s1 = _scene(id="s1", o_history=[days_ago(1)], o_counter=1, performer_ids=["p1"])
    s2 = _scene(id="s2", o_history=[days_ago(2)], o_counter=1, performer_ids=["p2"])
    shares = alg.trailing_category_shares([s1, s2], NOW, cfg, attr="performer_ids")
    assert math.isclose(shares["p1"] + shares["p2"], 1.0)
    assert math.isclose(shares["p1"], 0.5)

def test_apply_satiation_damps_only_overexposed_categories():
    cfg = Settings()
    # p is binged this week (share 1.0 → ×0.3); q has no recent activity (×1.0)
    binge = [_scene(id=f"b{i}", o_history=[days_ago(1)], o_counter=1,
                    performer_ids=["p"]) for i in range(4)]
    out = alg.apply_satiation({"performers": {"p": 0.8, "q": 0.8}, "tags": {}},
                              binge, NOW, cfg)
    assert math.isclose(out["performers"]["p"], 0.8 * 0.3)   # damped to floor
    assert out["performers"]["q"] == 0.8                     # untouched

def test_quality_prior_in_unit_range_and_rewards_resolution():
    cfg = Settings()
    hi = _scene(height=2160, organized=True, marker_count=10)
    lo = _scene(height=360, organized=False, marker_count=0)
    qa = alg.quality_prior(hi, dur_median=None, dur_scale=None, cfg=cfg)
    qb = alg.quality_prior(lo, dur_median=None, dur_scale=None, cfg=cfg)
    assert 0.0 <= qb <= qa <= 1.0
    assert qa > qb
