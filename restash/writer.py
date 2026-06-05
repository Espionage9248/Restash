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


_UPDATE_FIELD = {"scene": ("sceneUpdate", "SceneUpdateInput"),
                 "performer": ("performerUpdate", "PerformerUpdateInput")}


def aliased_update_mutation(entity: str, n: int) -> str:
    """Build a single GraphQL mutation with n aliased <entity>Update calls, each
    taking its own input variable ($i0, $i1, ...). Works for both partial-write
    and remove inputs (the input shape is decided by the caller's variables)."""
    field, itype = _UPDATE_FIELD[entity]
    decls = ", ".join(f"$i{k}: {itype}!" for k in range(n))
    body = "\n".join(f"  u{k}: {field}(input: $i{k}) {{ id }}" for k in range(n))
    return f"mutation({decls}) {{\n{body}\n}}"


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _call_with_retry(stash, query: str, variables: dict, cfg):
    """Call the GraphQL endpoint, retrying on ANY transport exception with
    exponential backoff (stashapi raises generic Exceptions; we treat any failure
    as retryable up to write_max_retries)."""
    last_exc = None
    for attempt in range(cfg.write_max_retries + 1):
        try:
            return stash.call_GQL(query, variables)
        except Exception as exc:   # noqa: BLE001 — any transport failure is retryable
            last_exc = exc
            if attempt < cfg.write_max_retries:
                time.sleep(cfg.write_backoff_base * (2 ** attempt))
    raise last_exc


def _count_succeeded(result, n: int) -> int:
    """How many of the n aliased updates (u0..u{n-1}) actually committed.
    stashapi returns HTTP 200 + a data dict even when some aliases error (the
    failed ones come back as null), so a batch is NOT necessarily all-or-nothing.
    Count only the non-null aliases. If the response shape is unrecognized, assume
    all n committed (we cannot prove a failure) rather than under-reporting."""
    if not isinstance(result, dict):
        return n
    return sum(1 for k in range(n) if result.get(f"u{k}") is not None)


def write_scores(stash, entity: str, scored: dict, existing_custom_fields: dict,
                 cfg, now_iso: str) -> dict:
    """Partial-write restash_* for changed entities only, in aliased batches.
    `scored` maps id → SceneScore/PerformerScore; `existing_custom_fields` maps id →
    that entity's current custom_fields (for skip-unchanged). Honors write_limit
    (subset-first gate). Returns {written, skipped, would_write, failed} where
    `written`/`failed` count only server-acknowledged (non-null) aliases."""
    build = scene_partial if entity == "scene" else performer_partial
    pending = []
    skipped = 0
    for eid, score in scored.items():
        partial = build(score, now_iso)
        if not needs_write(existing_custom_fields.get(eid) or {}, partial):
            skipped += 1
            continue
        pending.append({"id": str(eid), "custom_fields": {"partial": partial}})

    would_write = len(pending)
    if cfg.write_limit and would_write > cfg.write_limit:
        pending = pending[:cfg.write_limit]

    written = 0
    failed = 0
    for batch in _chunks(pending, cfg.write_chunk_size):
        query = aliased_update_mutation(entity, len(batch))
        variables = {f"i{k}": inp for k, inp in enumerate(batch)}
        result = _call_with_retry(stash, query, variables, cfg)
        ok = _count_succeeded(result, len(batch))
        written += ok
        failed += len(batch) - ok
    return {"written": written, "skipped": skipped, "would_write": would_write,
            "failed": failed}


def clear_scores(stash, entity: str, ids: list, cfg) -> int:
    """Remove all restash_* keys from the given entities via CustomFieldsInput.remove
    (v0.30+), in aliased batches. Leaves every other custom field untouched."""
    inputs = [{"id": str(i), "custom_fields": {"remove": RESTASH_KEYS}} for i in ids]
    cleared = 0
    for batch in _chunks(inputs, cfg.write_chunk_size):
        query = aliased_update_mutation(entity, len(batch))
        variables = {f"i{k}": inp for k, inp in enumerate(batch)}
        result = _call_with_retry(stash, query, variables, cfg)
        cleared += _count_succeeded(result, len(batch))
    return cleared
