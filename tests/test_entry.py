import types
import restash as entry
import config

def test_parse_input_extracts_mode_and_settings():
    payload = {"server_connection": {"Scheme": "http"},
               "args": {"mode": "dry"}, "plugin_config": {"cooldownDays": 7}}
    mode, conn, settings = entry.parse_input(payload)
    assert mode == "dry"
    assert conn == {"Scheme": "http"}
    assert settings.cooldown_days == 7.0

def test_parse_input_defaults_mode_to_dry():
    mode, _, _ = entry.parse_input({})
    assert mode == "dry"

def test_run_dispatches_dry(monkeypatch):
    captured = {}
    fake_io = types.SimpleNamespace(
        connect=lambda c: "STASH",
        ensure_schema=lambda s: {"scene_custom_fields": True,
                                 "custom_fields_remove": True},
    )
    monkeypatch.setattr(entry, "stash_io", fake_io)
    monkeypatch.setattr(entry, "_run_dry",
                        lambda stash, settings: captured.setdefault("dry", True) and 0)
    rc = entry.run({"args": {"mode": "dry"}})
    assert rc == 0 and captured.get("dry") is True

def test_run_dispatches_full(monkeypatch):
    captured = {}
    fake_io = types.SimpleNamespace(
        connect=lambda c: "STASH",
        ensure_schema=lambda s: {"scene_custom_fields": True, "custom_fields_remove": True})
    monkeypatch.setattr(entry, "stash_io", fake_io)
    monkeypatch.setattr(entry, "_run_full",
                        lambda stash, settings: captured.setdefault("full", True) and 0)
    assert entry.run({"args": {"mode": "full"}}) == 0 and captured["full"] is True

def test_run_dispatches_clear(monkeypatch):
    captured = {}
    fake_io = types.SimpleNamespace(
        connect=lambda c: "STASH",
        ensure_schema=lambda s: {"scene_custom_fields": True, "custom_fields_remove": True})
    monkeypatch.setattr(entry, "stash_io", fake_io)
    monkeypatch.setattr(entry, "_run_clear",
                        lambda stash, settings: captured.setdefault("clear", True) and 0)
    assert entry.run({"args": {"mode": "clear"}}) == 0 and captured["clear"] is True

def test_parse_input_reads_write_limit_from_args():
    payload = {"args": {"mode": "full", "write_limit": 5}}
    mode, _, settings = entry.parse_input(payload)
    assert mode == "full" and settings.write_limit == 5

def test_parse_input_reads_scene_ids_from_args():
    payload = {"args": {"mode": "full", "scene_ids": [10, "22"]}}
    mode, _, settings = entry.parse_input(payload)
    assert mode == "full" and settings.write_only_scene_ids == ("10", "22")

def test_run_full_targeted_writes_only_named_scenes(monkeypatch):
    import types
    calls = []
    Scene = lambda i: types.SimpleNamespace(id=i, custom_fields={}, favorite=False, rating100=None)
    fake_scenes = [Scene("1"), Scene("2"), Scene("3")]
    fake_perfs = [types.SimpleNamespace(id="9", custom_fields={}, favorite=False, rating100=None)]
    fake_io = types.SimpleNamespace(
        utcnow=entry.stash_io.utcnow,
        fetch_scenes=lambda s: fake_scenes,
        fetch_performers=lambda s: fake_perfs,
        resolve_tag_id=lambda s, n: None,
        filter_excluded=lambda sc, pf, ex: (sc, pf))
    fake_algo = types.SimpleNamespace(
        build_affinities=lambda *a, **k: {},
        score_scenes=lambda *a, **k: {"1": object(), "2": object(), "3": object()},
        score_performers=lambda *a, **k: {"9": object()})
    clear_calls = []
    def fake_write_scores(stash, entity, scored, existing, cfg, now_iso):
        calls.append((entity, sorted(scored.keys())))
        return {"written": len(scored), "skipped": 0, "would_write": len(scored)}
    fake_writer = types.SimpleNamespace(
        write_scores=fake_write_scores,
        clear_scores=lambda stash, entity, ids, cfg: clear_calls.append((entity, ids)) or 0,
        RESTASH_KEYS=entry.writer.RESTASH_KEYS)
    monkeypatch.setattr(entry, "stash_io", fake_io)
    monkeypatch.setattr(entry, "algorithm", fake_algo)
    monkeypatch.setattr(entry, "writer", fake_writer)
    rc = entry._run_full("STASH", config.Settings(write_only_scene_ids=("2",)))
    assert rc == 0
    assert ("scene", ["2"]) in calls       # only the targeted scene written
    assert ("performer", []) in calls       # performers skipped in targeted mode
    # D8 must be bypassed in targeted mode: clear_scores only ever gets empty id lists
    assert all(ids == [] for _, ids in clear_calls)
