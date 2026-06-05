import math
import pytest
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

def test_build_affinities_returns_three_classes_in_unit_range():
    cfg = Settings()
    scenes = [
        _scene(id="a", o_history=[days_ago(1)], o_counter=1,
               performer_ids=["p1"], tag_ids=["t1"], studio_id="st1"),
        _scene(id="b", play_history=[days_ago(1)], play_count=1, play_duration=90.0,
               performer_ids=["p2"], tag_ids=["t2"], studio_id="st2"),
    ]
    aff = alg.build_affinities(scenes, NOW, cfg, favorites=set(), ratings={})
    for cls in ("performers", "tags", "studios"):
        assert all(-1.0 <= v <= 1.0 for v in aff[cls].values())
    assert aff["performers"]["p1"] > aff["performers"]["p2"]  # o beats play

def test_scene_base_blends_by_confidence():
    cfg = Settings()
    aff = {"performers": {"p1": 0.8}, "tags": {}, "studios": {}}
    tagcounts = {}
    # scene with lots of direct o-history → confidence high → direct dominates
    hot = _scene(id="h", o_history=[days_ago(1)] * 6, o_counter=6, performer_ids=["p1"])
    comp = alg.scene_base(hot, aff, tagcounts, None, None, cfg, NOW)
    assert comp["confidence"] == 1.0
    assert comp["base"] > 0.5

def test_scene_base_uses_ingredients_when_no_history():
    cfg = Settings()
    aff = {"performers": {"p1": 0.9}, "tags": {}, "studios": {}}
    cold = _scene(id="c", performer_ids=["p1"])   # no events
    comp = alg.scene_base(cold, aff, {}, None, None, cfg, NOW)
    assert comp["confidence"] == 0.0
    assert math.isclose(comp["base"], comp["ingredients"])

def test_score_scenes_emits_one_score_each_and_ranks_1_to_100():
    cfg = Settings()
    scenes = [
        _scene(id="hot", o_history=[days_ago(2)] * 4, o_counter=4, performer_ids=["p1"]),
        _scene(id="cold", performer_ids=["p2"], created_at=days_ago(1000)),
        _scene(id="mid", play_history=[days_ago(40)], play_count=1,
               play_duration=80.0, performer_ids=["p1"]),
    ]
    scores = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    assert set(scores) == {"hot", "cold", "mid"}
    assert all(1 <= s.restash_score <= 100 for s in scores.values())
    assert max(s.restash_score for s in scores.values()) == 100

def test_just_watched_scene_is_buried():
    cfg = Settings()
    scenes = [
        _scene(id="just", o_history=[days_ago(0)], o_counter=1, performer_ids=["p1"]),
        _scene(id="old", o_history=[days_ago(200)], o_counter=1, performer_ids=["p1"]),
    ]
    scores = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    assert scores["just"].restash_score < scores["old"].restash_score

def test_score_scenes_is_deterministic_same_day():
    cfg = Settings()
    scenes = [_scene(id=f"s{i}", play_history=[days_ago(i + 3)], play_count=1,
                     play_duration=50.0, performer_ids=["p1"]) for i in range(10)]
    a = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    b = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    assert {k: v.restash_score for k, v in a.items()} == \
           {k: v.restash_score for k, v in b.items()}

def test_wildcards_promote_low_confidence_midpack():
    cfg = Settings()
    # 100 no-history scenes spread across the percentile range by created_at
    scenes = [_scene(id=f"w{i}", created_at=days_ago(i * 5 + 1)) for i in range(100)]
    scores = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    wild = [s for s in scores.values() if s.wildcard]
    assert len(wild) == int(100 * cfg.wildcard_percent / 100)   # 2
    assert all(85 <= s.restash_score <= 95 for s in wild)
    # deterministic: same day → same wildcard set
    again = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    assert {s.id for s in scores.values() if s.wildcard} == \
           {s.id for s in again.values() if s.wildcard}


def test_last_engagement_uses_last_played_at_when_newer_than_play_history():
    cfg = Settings()
    # play_history is stale (40d) but last_played_at is recent (1d): anchor must be 1d.
    s = _scene(id="lp", play_history=[days_ago(40)], play_count=2,
               play_duration=50.0, last_played_at=days_ago(1), performer_ids=["p1"])
    scores = alg.score_scenes([s, _scene(id="other", performer_ids=["p2"])],
                              cfg, NOW, "2026-06-05")
    # fresh_d should reflect the 1-day anchor (just-watched), not 40 days.
    assert scores["lp"].components["fresh_d"] == pytest.approx(1.0, abs=0.01)


def _perf(**kw):
    base = dict(id="p", name="N", favorite=False, rating100=None, o_counter=0,
                scene_count=0, tag_ids=[], created_at=days_ago(400), custom_fields={})
    base.update(kw)
    return models.PerformerData(**base)

def test_score_performers_ranks_and_uses_best_scenes():
    cfg = Settings()
    scenes = [
        _scene(id="s1", o_history=[days_ago(2)] * 3, o_counter=3, performer_ids=["good"]),
        _scene(id="s2", performer_ids=["meh"], created_at=days_ago(900)),
    ]
    scene_scores = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    aff = alg.build_affinities(scenes, NOW, cfg, set(), {})
    performers = [_perf(id="good", scene_count=1), _perf(id="meh", scene_count=1)]
    ps = alg.score_performers(performers, scenes, scene_scores, aff, cfg, NOW)
    assert ps["good"].restash_score >= ps["meh"].restash_score
    assert all(1 <= p.restash_score <= 100 for p in ps.values())

def test_favorite_floor_at_60th_percentile():
    cfg = Settings()
    scenes = [_scene(id=f"s{i}", performer_ids=[f"p{i}"]) for i in range(10)]
    ss = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    aff = alg.build_affinities(scenes, NOW, cfg, set(), {})
    performers = [_perf(id=f"p{i}", scene_count=1) for i in range(10)]
    performers[0].favorite = True   # p0 would otherwise rank low/mid
    ps = alg.score_performers(performers, scenes, ss, aff, cfg, NOW)
    assert ps["p0"].restash_score >= 60


def test_empty_library_does_not_crash():
    assert alg.score_scenes([], Settings(), NOW, "2026-06-05") == {}

def test_scene_with_no_file_duration_and_zero_history():
    cfg = Settings()
    s = _scene(id="x", file_duration=None, height=None, created_at=days_ago(5))
    scores = alg.score_scenes([s], cfg, NOW, "2026-06-05")
    assert scores["x"].restash_score >= 1   # novelty + quality, no crash

def test_fresh_library_all_zero_history_scores_by_prior_and_novelty():
    cfg = Settings()
    scenes = [_scene(id=f"n{i}", height=1080 + i, created_at=days_ago(i + 1))
              for i in range(5)]
    scores = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    assert len(scores) == 5
    assert all(s.n_events == 0 for s in scores.values())

def test_next_day_differs_only_by_jitter_drift():
    cfg = Settings()
    scenes = [_scene(id=f"s{i}", o_history=[days_ago(50)], o_counter=1,
                     performer_ids=["p"]) for i in range(20)]
    today = alg.score_scenes(scenes, cfg, NOW, "2026-06-05")
    tomorrow = alg.score_scenes(scenes, cfg, NOW, "2026-06-06")
    # different seed → at least some ranks move, but bounded set of ids unchanged
    assert set(today) == set(tomorrow)
    moved = sum(today[k].restash_score != tomorrow[k].restash_score for k in today)
    assert moved >= 1


def test_no_abandonment_penalty_when_completion_high():
    # D11: fully-watched scene with resume_time reset to 0 must NOT be penalized.
    s = _scene(play_history=[days_ago(1)], play_count=1, play_duration=95.0,
               resume_time=0.0, file_duration=100.0)  # completion 0.95, resume 0, no o
    ev = alg.extract_events(s, Settings())
    assert not any(e.kind == "penalty" for e in ev)

def test_abandonment_penalty_still_fires_on_low_completion():
    # genuinely sampled-and-bailed: low completion + early resume + no o → penalized.
    s = _scene(play_history=[days_ago(1)], play_count=1, play_duration=10.0,
               resume_time=5.0, file_duration=100.0)  # completion 0.10
    ev = alg.extract_events(s, Settings())
    assert any(e.kind == "penalty" and e.value == -0.5 for e in ev)

def test_abandonment_completion_gate_is_tunable():
    # raising the gate above the scene's completion re-enables the penalty.
    cfg = Settings(abandonment_completion_max=0.99)
    s = _scene(play_history=[days_ago(1)], play_count=1, play_duration=95.0,
               resume_time=0.0, file_duration=100.0)  # completion 0.95 < 0.99
    ev = alg.extract_events(s, cfg)
    assert any(e.kind == "penalty" for e in ev)


def test_performer_best_material_shrinks_toward_prior_by_evidence():
    # D12: two performers both have only top-scoring scenes (raw term 1.0); a third
    # 'low' performer drags the population prior below 1.0 so shrinkage is visible.
    cfg = Settings()
    solo_scene = _scene(id="ss", performer_ids=["solo"])
    pro_scenes = [_scene(id=f"ps{i}", performer_ids=["prolific"]) for i in range(5)]
    low_scene = _scene(id="ls", performer_ids=["low"])
    scenes = [solo_scene, *pro_scenes, low_scene]

    def _ss(sid, score):
        return models.SceneScore(id=sid, raw=0.0, restash_score=score,
                                 percentile=score / 100, n_events=0, wildcard=False,
                                 components={})
    scene_scores = {"ss": _ss("ss", 100), "ls": _ss("ls", 10)}
    for i in range(5):
        scene_scores[f"ps{i}"] = _ss(f"ps{i}", 100)
    aff = {"performers": {}, "tags": {}, "studios": {}}
    performers = [_perf(id="solo"), _perf(id="prolific"), _perf(id="low")]
    ps = alg.score_performers(performers, scenes, scene_scores, aff, cfg, NOW)

    solo_term = ps["solo"].components["scenes"]
    pro_term = ps["prolific"].components["scenes"]
    assert pro_term > solo_term        # more scenes → less shrinkage → higher term
    assert solo_term < 1.0             # single-scene performer pulled below the ceiling
    assert ps["prolific"].restash_score >= ps["solo"].restash_score

def test_performer_shrinkage_k_zero_is_noop():
    # k=0 → no shrinkage → single strong scene keeps the full term.
    cfg = Settings(perf_scenes_shrinkage_k=0.0)
    scenes = [_scene(id="x", performer_ids=["solo"]),
              _scene(id="y", performer_ids=["low"])]
    scene_scores = {
        "x": models.SceneScore(id="x", raw=0.0, restash_score=100, percentile=1.0,
                               n_events=0, wildcard=False, components={}),
        "y": models.SceneScore(id="y", raw=0.0, restash_score=10, percentile=0.1,
                               n_events=0, wildcard=False, components={})}
    aff = {"performers": {}, "tags": {}, "studios": {}}
    ps = alg.score_performers([_perf(id="solo"), _perf(id="low")], scenes,
                              scene_scores, aff, cfg, NOW)
    assert ps["solo"].components["scenes"] == 1.0   # unshrunk
