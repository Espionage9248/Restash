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

def test_run_rejects_write_modes_in_this_build(monkeypatch):
    fake_io = types.SimpleNamespace(
        connect=lambda c: "STASH",
        ensure_schema=lambda s: {"scene_custom_fields": True,
                                 "custom_fields_remove": True})
    monkeypatch.setattr(entry, "stash_io", fake_io)
    rc = entry.run({"args": {"mode": "full"}})
    assert rc == 0   # logs "not implemented", exits cleanly, writes nothing
