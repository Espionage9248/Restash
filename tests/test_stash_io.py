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
