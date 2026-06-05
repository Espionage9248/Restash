import pytest
import stash_io

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

from datetime import datetime, timezone

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
