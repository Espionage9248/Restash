import json
import state
import config


def test_fingerprint_changes_on_base_affecting_setting():
    a = state.settings_fingerprint(config.Settings())
    b = state.settings_fingerprint(config.Settings(direct_scale=99.0))
    assert a != b


def test_fingerprint_stable_on_freshness_only_setting():
    a = state.settings_fingerprint(config.Settings())
    b = state.settings_fingerprint(config.Settings(jitter_amplitude=0.5,
                                                   cooldown_days=99.0))
    assert a == b


def test_save_then_load_round_trips(tmp_path):
    p = str(tmp_path / "restash_state.json")
    state.save_state(p, settings=config.Settings(),
                     affinities={"performers": {"7": 0.5}},
                     scenes={"1": {"base": 0.2, "n_events": 0,
                                   "created_at": "2026-01-01T00:00:00Z",
                                   "last_engagement": None, "perf_ids": ["7"]}},
                     written_at="2026-06-08T00:00:00Z")
    loaded = state.load_state(p)
    assert loaded["format_version"] == state.STATE_FORMAT_VERSION
    assert loaded["scenes"]["1"]["base"] == 0.2
    assert loaded["affinities"]["performers"]["7"] == 0.5


def test_save_is_atomic_no_temp_left(tmp_path):
    p = str(tmp_path / "restash_state.json")
    state.save_state(p, settings=config.Settings(), affinities={}, scenes={},
                     written_at="2026-06-08T00:00:00Z")
    leftovers = [f.name for f in tmp_path.iterdir() if f.name != "restash_state.json"]
    assert leftovers == []


def test_load_missing_returns_none(tmp_path):
    assert state.load_state(str(tmp_path / "nope.json")) is None


def test_load_corrupt_returns_none(tmp_path):
    p = tmp_path / "restash_state.json"
    p.write_text("{ this is not json")
    assert state.load_state(str(p)) is None


def test_is_valid_detects_settings_drift(tmp_path):
    p = str(tmp_path / "restash_state.json")
    state.save_state(p, settings=config.Settings(), affinities={}, scenes={},
                     written_at="2026-06-08T00:00:00Z")
    st = state.load_state(p)
    ok, _ = state.is_valid(st, config.Settings())
    assert ok is True
    bad, reason = state.is_valid(st, config.Settings(direct_scale=99.0))
    assert bad is False and "settings" in reason


def test_is_valid_none_state():
    ok, reason = state.is_valid(None, config.Settings())
    assert ok is False and reason
