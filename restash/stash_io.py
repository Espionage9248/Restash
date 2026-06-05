from __future__ import annotations
from datetime import datetime, timezone

from stashapi.stashapp import StashInterface  # noqa: provided by stashapp-tools


class UnsupportedSchema(Exception):
    pass


def connect(server_connection: dict) -> StashInterface:
    return StashInterface(server_connection)


_SCENE_INPUT_PROBE = """
query { __type(name: "SceneUpdateInput") { inputFields { name } } }
"""
_CUSTOMFIELDS_PROBE = """
query { __type(name: "CustomFieldsInput") { inputFields { name } } }
"""


def ensure_schema(stash) -> dict:
    """Probe introspection; raise UnsupportedSchema if scene custom_fields are
    absent. Returns a capabilities dict (also records remove support)."""
    scene_fields = _input_field_names(stash, _SCENE_INPUT_PROBE)
    cf_fields = _input_field_names(stash, _CUSTOMFIELDS_PROBE)
    caps = {
        "scene_custom_fields": "custom_fields" in scene_fields,
        "custom_fields_remove": "remove" in cf_fields,
    }
    if not caps["scene_custom_fields"]:
        raise UnsupportedSchema(
            "This Stash build lacks scene custom_fields on SceneUpdateInput. "
            "Restash needs scene custom_fields (current stable/develop). "
            "Upgrade Stash, then re-run.")
    return caps


def _input_field_names(stash, query: str) -> set[str]:
    result = stash.call_GQL(query)
    type_obj = (result or {}).get("__type") or {}
    return {f["name"] for f in (type_obj.get("inputFields") or [])}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
