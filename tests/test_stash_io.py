import pytest
import stash_io
from datetime import datetime, timezone

class FakeStash:
    def __init__(self, schema_types):
        self._schema_types = schema_types
        self.calls = []
    def call_GQL(self, query, variables=None):
        self.calls.append((query, variables))
        if "__type" in query and "SceneUpdateInput" in query:
            present = "custom_fields" in self._schema_types.get("SceneUpdateInput", [])
            fields = [{"name": "custom_fields"}] if present else []
            return {"__type": {"inputFields": fields}}
        if "__type" in query and "CustomFieldsInput" in query:
            present = "remove" in self._schema_types.get("CustomFieldsInput", [])
            fields = [{"name": "remove"}] if present else []
            return {"__type": {"inputFields": fields}}
        return {}

def test_ensure_schema_passes_when_supported():
    fake = FakeStash({"SceneUpdateInput": ["custom_fields"],
                      "CustomFieldsInput": ["remove"]})
    caps = stash_io.ensure_schema(fake)
    assert caps["scene_custom_fields"] is True
    assert caps["custom_fields_remove"] is True

def test_ensure_schema_raises_when_scene_custom_fields_missing():
    fake = FakeStash({"SceneUpdateInput": [], "CustomFieldsInput": ["remove"]})
    with pytest.raises(stash_io.UnsupportedSchema) as ei:
        stash_io.ensure_schema(fake)
    assert "custom_fields" in str(ei.value)

def test_map_scene_handles_missing_file_and_nulls():
    raw = {"id": "1", "title": None, "play_history": [], "o_history": [],
           "play_count": 0, "o_counter": 0, "play_duration": 0,
           "resume_time": None, "last_played_at": None, "files": [],
           "date": None, "created_at": "2026-01-02T03:04:05Z", "rating100": None,
           "tags": [], "performers": [], "studio": None, "scene_markers": [],
           "organized": False, "custom_fields": {}}
    s = stash_io.map_scene(raw)
    assert s.has_file is False
    assert s.file_duration is None
    assert s.created_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert s.title == ""

def test_map_scene_extracts_fields_and_histories():
    raw = {"id": "7", "title": "T", "play_history": ["2026-06-01T00:00:00Z"],
           "o_history": ["2026-06-02T00:00:00Z"], "play_count": 1, "o_counter": 1,
           "play_duration": 100, "resume_time": 12.5,
           "last_played_at": "2026-06-01T00:00:00Z",
           "files": [{"duration": 200.0, "height": 1080}],
           "date": "2025-01-01", "created_at": "2026-01-01T00:00:00Z",
           "rating100": 80, "tags": [{"id": "t1"}], "performers": [{"id": "p1"}],
           "studio": {"id": "st1"}, "scene_markers": [{"id": "m1"}, {"id": "m2"}],
           "organized": True, "custom_fields": {"foo": "bar"}}
    s = stash_io.map_scene(raw)
    assert s.file_duration == 200.0 and s.height == 1080
    assert s.tag_ids == ["t1"] and s.performer_ids == ["p1"] and s.studio_id == "st1"
    assert s.marker_count == 2 and s.organized is True
    assert len(s.play_history) == 1 and len(s.o_history) == 1
    assert s.custom_fields == {"foo": "bar"}

def test_fetch_scenes_paginates(monkeypatch):
    pages = [
        [{"id": "1", "files": [], "created_at": "2026-01-01T00:00:00Z"}],
        [{"id": "2", "files": [], "created_at": "2026-01-01T00:00:00Z"}],
        [],
    ]
    calls = {"n": 0}
    class S:
        def call_GQL(self, query, variables=None):
            idx = variables["filter"]["page"] - 1
            data = pages[idx] if idx < len(pages) else []
            calls["n"] += 1
            return {"findScenes": {"scenes": data}}
    scenes = stash_io.fetch_scenes(S(), per_page=1)
    assert [s.id for s in scenes] == ["1", "2"]
    assert calls["n"] >= 3   # two pages + the empty terminator


def test_parse_dt_degrades_on_bad_input_without_raising():
    # malformed / non-string / empty must return None, never raise (D10/§7 robustness)
    assert stash_io._parse_dt("N/A") is None
    assert stash_io._parse_dt("2026/01/01 12:00") is None
    assert stash_io._parse_dt(1234567890) is None
    assert stash_io._parse_dt(None) is None
    assert stash_io._parse_dt("") is None
    # a valid date-only string still parses to tz-aware UTC midnight
    d = stash_io._parse_dt("2025-01-01")
    assert d == datetime(2025, 1, 1, tzinfo=timezone.utc)

def test_map_performer_handles_nulls_and_extracts_fields():
    raw = {"id": 7, "name": None, "favorite": True, "rating100": None,
           "o_counter": 0, "scene_count": 3, "created_at": "2026-01-01T00:00:00Z",
           "tags": [{"id": "t1"}, {"id": "t2"}], "custom_fields": {"k": "v"}}
    p = stash_io.map_performer(raw)
    assert p.id == "7"            # coerced to str
    assert p.name == ""           # null → ""
    assert p.favorite is True
    assert p.rating100 is None
    assert p.scene_count == 3
    assert p.tag_ids == ["t1", "t2"]
    assert p.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert p.custom_fields == {"k": "v"}

def test_fetch_performers_paginates(monkeypatch):
    pages = [
        [{"id": "1", "created_at": "2026-01-01T00:00:00Z"}],
        [{"id": "2", "created_at": "2026-01-01T00:00:00Z"}],
        [],
    ]
    calls = {"n": 0}
    class S:
        def call_GQL(self, query, variables=None):
            idx = variables["filter"]["page"] - 1
            data = pages[idx] if idx < len(pages) else []
            calls["n"] += 1
            return {"findPerformers": {"performers": data}}
    performers = stash_io.fetch_performers(S(), per_page=1)
    assert [p.id for p in performers] == ["1", "2"]
    assert calls["n"] >= 3

def test_resolve_exclude_tag_returns_id_or_none():
    class S:
        def call_GQL(self, query, variables=None):
            if "findTags" in query:
                name = variables["filter"]["q"]
                if name == "[Restash: Exclude]":
                    return {"findTags": {"tags": [{"id": "99",
                            "name": "[Restash: Exclude]"}]}}
                return {"findTags": {"tags": []}}
            return {}
    assert stash_io.resolve_tag_id(S(), "[Restash: Exclude]") == "99"
    assert stash_io.resolve_tag_id(S(), "Nonexistent") is None

def test_stash_io_contains_no_mutations():
    # G2: this build must not write. No *Update/bulk* mutation strings allowed.
    import pathlib
    src = pathlib.Path(stash_io.__file__).read_text()
    for forbidden in ("sceneUpdate", "bulkSceneUpdate", "performerUpdate",
                      "bulkPerformerUpdate", "mutation"):
        assert forbidden not in src, f"write path leaked into stash_io: {forbidden}"

import models as _models
from datetime import datetime as _dt, timezone as _tz

def _sd(id, has_file=True, tag_ids=None):
    return _models.SceneData(
        id=id, title="t", play_history=[], o_history=[], play_count=0,
        o_counter=0, play_duration=0.0, resume_time=None, last_played_at=None,
        file_duration=100.0 if has_file else None, height=1080, marker_count=0,
        organized=False, date=None, created_at=_dt(2026, 1, 1, tzinfo=_tz.utc),
        rating100=None, tag_ids=tag_ids or [], performer_ids=[], studio_id=None,
        custom_fields={}, has_file=has_file)

def _pd(id, tag_ids=None):
    return _models.PerformerData(
        id=id, name="N", favorite=False, rating100=None, o_counter=0,
        scene_count=0, tag_ids=tag_ids or [], created_at=_dt(2026, 1, 1, tzinfo=_tz.utc),
        custom_fields={})

def test_filter_excluded_none_drops_fileless_scenes_keeps_all_performers():
    scenes = [_sd("s1", has_file=True), _sd("s2", has_file=False)]
    performers = [_pd("p1"), _pd("p2", tag_ids=["99"])]
    kept_scenes, kept_perf = stash_io.filter_excluded(scenes, performers, None)
    assert [s.id for s in kept_scenes] == ["s1"]          # fileless dropped
    assert [p.id for p in kept_perf] == ["p1", "p2"]      # performers untouched when no exclude id

def test_filter_excluded_drops_tagged_scenes_and_performers():
    scenes = [_sd("keep", tag_ids=["1"]), _sd("excl", tag_ids=["99"]),
              _sd("nofile", has_file=False, tag_ids=["1"])]
    performers = [_pd("pk", tag_ids=["1"]), _pd("pe", tag_ids=["99"])]
    kept_scenes, kept_perf = stash_io.filter_excluded(scenes, performers, "99")
    assert [s.id for s in kept_scenes] == ["keep"]        # excl(tagged) + nofile dropped
    assert [p.id for p in kept_perf] == ["pk"]            # pe(tagged) dropped

def test_filter_excluded_returns_tuple_of_two_lists():
    out = stash_io.filter_excluded([], [], None)
    assert out == ([], [])

def test_fetch_scenes_light_maps_minimal_fields(monkeypatch):
    import stash_io
    pages = [[{"id": 1, "last_played_at": "2026-05-01T00:00:00Z",
               "play_count": 3, "o_counter": 1,
               "custom_fields": {"restash_score": 42}}], []]
    calls = {"n": 0}

    class FakeStash:
        def call_GQL(self, query, variables=None):
            i = calls["n"]; calls["n"] += 1
            return {"findScenes": {"scenes": pages[i] if i < len(pages) else []}}

    out = stash_io.fetch_scenes_light(FakeStash())
    assert len(out) == 1
    row = out[0]
    assert row["id"] == "1"
    assert row["play_count"] == 3 and row["o_counter"] == 1
    assert row["custom_fields"] == {"restash_score": 42}
    # last_played_at parsed to an aware datetime
    assert row["last_played_at"].year == 2026


# --- fetch_plugin_settings (settings are read from the server, not the payload) ---

class _CfgStash:
    def __init__(self, result):
        self._result = result
    def call_GQL(self, query, variables=None):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

def test_fetch_plugin_settings_extracts_by_id():
    stash = _CfgStash({"configuration": {"plugins": {"restash": {"cooldownDays": 7}}}})
    assert stash_io.fetch_plugin_settings(stash, "restash") == {"cooldownDays": 7}

def test_fetch_plugin_settings_absent_plugin_returns_empty():
    stash = _CfgStash({"configuration": {"plugins": {"other": {"x": 1}}}})
    assert stash_io.fetch_plugin_settings(stash, "restash") == {}

def test_fetch_plugin_settings_on_error_returns_empty():
    stash = _CfgStash(RuntimeError("boom"))
    assert stash_io.fetch_plugin_settings(stash, "restash") == {}
