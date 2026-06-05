from __future__ import annotations
import json
import time

import models

RESTASH_KEYS = ["restash_score", "restash_raw", "restash_components", "restash_updated"]


def _round_components(components: dict) -> dict:
    out = {}
    for k, v in components.items():
        out[k] = round(v, 3) if isinstance(v, float) else v
    return out


def scene_partial(score: models.SceneScore, now_iso: str) -> dict:
    return {"restash_score": int(score.restash_score),
            "restash_raw": round(score.raw, 4),
            "restash_components": json.dumps(_round_components(score.components)),
            "restash_updated": now_iso}


def performer_partial(score: models.PerformerScore, now_iso: str) -> dict:
    return {"restash_score": int(score.restash_score),
            "restash_raw": round(score.raw, 4),
            "restash_components": json.dumps(_round_components(score.components)),
            "restash_updated": now_iso}


def needs_write(existing_custom_fields: dict, new_partial: dict) -> bool:
    """Skip when the headline score is unchanged (spec §2.4). Compared as strings
    because Stash's custom_fields Map may return ints or strings. The volatile
    restash_updated timestamp is intentionally NOT part of the comparison."""
    existing = existing_custom_fields.get("restash_score")
    if existing is None:
        return True
    return str(existing) != str(new_partial.get("restash_score"))
