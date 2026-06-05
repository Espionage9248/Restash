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


SCENE_FRAGMENT = """
id title organized rating100 date created_at resume_time play_duration
play_count o_counter last_played_at play_history o_history
files { duration height }
tags { id } performers { id } studio { id } scene_markers { id }
custom_fields
"""

PERFORMER_FRAGMENT = """
id name favorite rating100 o_counter scene_count created_at tags { id } custom_fields
"""

_FIND_SCENES = """
query($filter: FindFilterType) {
  findScenes(filter: $filter) { scenes { %s } }
}
""" % SCENE_FRAGMENT

_FIND_PERFORMERS = """
query($filter: FindFilterType) {
  findPerformers(filter: $filter) { performers { %s } }
}
""" % PERFORMER_FRAGMENT


def _parse_dt(value):
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            # date-only (production date)
            dt = datetime.fromisoformat(text + "T00:00:00+00:00")
        except ValueError:
            return None   # unparseable: degrade to None, don't abort the read (D10/§7)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_dt_list(values):
    return [d for d in (_parse_dt(v) for v in (values or [])) if d]


def map_scene(raw: dict):
    import models
    files = raw.get("files") or []
    first = files[0] if files else {}
    studio = raw.get("studio") or {}
    return models.SceneData(
        id=str(raw["id"]),
        title=raw.get("title") or "",
        play_history=_parse_dt_list(raw.get("play_history")),
        o_history=_parse_dt_list(raw.get("o_history")),
        play_count=raw.get("play_count") or 0,
        o_counter=raw.get("o_counter") or 0,
        play_duration=float(raw.get("play_duration") or 0.0),
        resume_time=raw.get("resume_time"),
        last_played_at=_parse_dt(raw.get("last_played_at")),
        file_duration=(float(first["duration"]) if first.get("duration") else None),
        height=first.get("height"),
        marker_count=len(raw.get("scene_markers") or []),
        organized=bool(raw.get("organized")),
        date=_parse_dt(raw.get("date")),
        created_at=_parse_dt(raw.get("created_at")) or utcnow(),
        rating100=raw.get("rating100"),
        tag_ids=[str(t["id"]) for t in (raw.get("tags") or [])],
        performer_ids=[str(p["id"]) for p in (raw.get("performers") or [])],
        studio_id=str(studio["id"]) if studio.get("id") else None,
        custom_fields=raw.get("custom_fields") or {},
        has_file=bool(files),
    )


def map_performer(raw: dict):
    import models
    return models.PerformerData(
        id=str(raw["id"]),
        name=raw.get("name") or "",
        favorite=bool(raw.get("favorite")),
        rating100=raw.get("rating100"),
        o_counter=raw.get("o_counter") or 0,
        scene_count=raw.get("scene_count") or 0,
        tag_ids=[str(t["id"]) for t in (raw.get("tags") or [])],
        created_at=_parse_dt(raw.get("created_at")) or utcnow(),
        custom_fields=raw.get("custom_fields") or {},
    )


def _paginate(stash, query: str, root: str, sub: str, per_page: int, mapper,
              progress=None):
    out = []
    page = 1
    while True:
        variables = {"filter": {"per_page": per_page, "page": page,
                                "sort": "id", "direction": "ASC"}}
        result = stash.call_GQL(query, variables)
        batch = ((result or {}).get(root) or {}).get(sub) or []
        if not batch:
            break
        out.extend(mapper(item) for item in batch)
        if progress:
            progress(len(out))
        page += 1
    return out


def fetch_scenes(stash, per_page: int = 500, progress=None):
    return _paginate(stash, _FIND_SCENES, "findScenes", "scenes", per_page,
                     map_scene, progress)


def fetch_performers(stash, per_page: int = 500, progress=None):
    return _paginate(stash, _FIND_PERFORMERS, "findPerformers", "performers",
                     per_page, map_performer, progress)
