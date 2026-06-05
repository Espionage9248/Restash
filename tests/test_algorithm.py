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
