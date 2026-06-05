import types
import restash as entry

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
