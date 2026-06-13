from __future__ import annotations
import json
import pathlib
import sys

import algorithm
import config
import models
import report
import state
import stash_io
import writer
from stashapi import log   # stashapp-tools logging → drives Stash progress bar


PLUGIN_ID = "restash"


def parse_input(payload: dict):
    """Pull the bits Stash actually sends: the server connection and the task
    `args` (mode + any defaultArgs / dev overrides). Plugin SETTINGS are NOT in
    the payload — Stash delivers them only via the configuration query — so they
    are resolved later in run() against the live connection."""
    args = payload.get("args") or {}
    mode = args.get("mode") or "dry"
    conn = payload.get("server_connection") or {}
    return mode, conn, args


def build_settings(plugin_cfg: dict | None, args: dict) -> config.Settings:
    """Layer settings: dataclass defaults < Stash plugin settings < payload-arg
    overrides (write_limit / scene_ids — used for targeted and dev runs)."""
    settings = config.Settings.from_plugin_settings(plugin_cfg)
    if "write_limit" in args:
        settings.write_limit = int(args["write_limit"])
    if "scene_ids" in args:
        settings.write_only_scene_ids = tuple(str(i) for i in args["scene_ids"])
    return settings


def run(payload: dict) -> int:
    mode, conn, args = parse_input(payload)
    stash = stash_io.connect(conn)
    caps = stash_io.ensure_schema(stash)
    # Stash sends only server_connection + args — never the plugin settings — so
    # read them from the server here. A payload-provided plugin_config still wins
    # (used by tests and tools/run_local).
    plugin_cfg = stash_io.fetch_plugin_settings(stash, PLUGIN_ID)
    if payload.get("plugin_config"):
        plugin_cfg = {**plugin_cfg, **payload["plugin_config"]}
    settings = build_settings(plugin_cfg, args)
    log.info(f"Restash: schema OK (scene custom_fields, "
             f"remove={caps['custom_fields_remove']}). mode={mode}")
    if mode == "dry":
        return _run_dry(stash, settings)
    if mode == "full":
        return _run_full(stash, settings)
    if mode == "clear":
        return _run_clear(stash, settings)
    if mode == "refresh":
        return _run_refresh(stash, settings)
    log.error(f"Restash: unknown mode '{mode}'.")
    return 1


def _run_dry(stash, settings: config.Settings) -> int:
    now = stash_io.utcnow()
    date_seed = now.strftime("%Y-%m-%d")

    log.progress(0.05)
    scenes = stash_io.fetch_scenes(stash)
    log.info(f"Restash: read {len(scenes)} scenes.")
    log.progress(0.45)
    performers = stash_io.fetch_performers(stash)
    log.info(f"Restash: read {len(performers)} performers.")
    log.progress(0.60)

    exclude_id = stash_io.resolve_tag_id(stash, settings.exclude_tag_name)
    scenes, performers = stash_io.filter_excluded(scenes, performers, exclude_id)
    log.info(f"Restash: scoring {len(scenes)} scenes / {len(performers)} performers "
             f"(exclude tag id={exclude_id}).")

    favorites = {p.id for p in performers if p.favorite}
    ratings = ({p.id: p.rating100 for p in performers if p.rating100 is not None}
               if settings.respect_manual_ratings else {})

    aff = algorithm.build_affinities(scenes, now, settings, favorites, ratings)
    scene_scores = algorithm.score_scenes(scenes, settings, now, date_seed,
                                          favorites, ratings, aff)
    log.progress(0.85)
    performer_scores = algorithm.score_performers(performers, scenes, scene_scores,
                                                 aff, settings, now)
    log.progress(0.95)

    titles = {s.id: s.title for s in scenes}
    names = {p.id: p.name for p in performers}
    diag_rows, diag_summary = _watched_diagnostic(scenes, scene_scores, settings)
    summary = report.format_summary(len(scene_scores), len(performer_scores),
                                    would_write=len(scene_scores) + len(performer_scores),
                                    skipped=0)

    report_path = pathlib.Path(__file__).parent / "restash_dry_run.txt"
    report_path.write_text(
        "\n\n".join([
            report.format_scene_report(scene_scores, titles, top_n=30),
            report.format_performer_report(performer_scores, names, top_n=30),
            report.format_watched_diagnostic(diag_rows, diag_summary, top_n=20),
            summary,
        ]),
        encoding="utf-8",
    )

    for line in summary.splitlines():
        log.info(line)
    log.info(f"Restash: full report saved → {report_path}")
    log.progress(1.0)
    return 0


def _run_full(stash, settings: config.Settings) -> int:
    now = stash_io.utcnow()
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_seed = now.strftime("%Y-%m-%d")

    log.progress(0.05)
    scenes = stash_io.fetch_scenes(stash)
    performers = stash_io.fetch_performers(stash)
    log.info(f"Restash: read {len(scenes)} scenes / {len(performers)} performers.")
    log.progress(0.45)

    exclude_id = stash_io.resolve_tag_id(stash, settings.exclude_tag_name)
    kept_scenes, kept_performers = stash_io.filter_excluded(scenes, performers, exclude_id)
    kept_scene_ids = {s.id for s in kept_scenes}
    kept_perf_ids = {p.id for p in kept_performers}
    log.info(f"Restash: scoring {len(kept_scenes)} scenes / {len(kept_performers)} "
             f"performers (exclude tag id={exclude_id}).")

    favorites = {p.id for p in kept_performers if p.favorite}
    ratings = ({p.id: p.rating100 for p in kept_performers if p.rating100 is not None}
               if settings.respect_manual_ratings else {})

    aff = algorithm.build_affinities(kept_scenes, now, settings, favorites, ratings)
    scene_scores = algorithm.score_scenes(kept_scenes, settings, now, date_seed,
                                          favorites, ratings, aff)
    performer_scores = algorithm.score_performers(kept_performers, kept_scenes,
                                                  scene_scores, aff, settings, now)
    log.progress(0.70)

    scenes_cache = _build_scene_cache(kept_scenes, scene_scores)
    state.save_state(state.default_state_path(), settings=settings, affinities=aff,
                     scenes=scenes_cache, written_at=now_iso)
    log.info(f"Restash: wrote taste-model cache ({len(scenes_cache)} scenes) "
             f"to restash_state.json.")

    targeted = bool(settings.write_only_scene_ids)
    if targeted:
        target = set(settings.write_only_scene_ids)
        scene_scores = {sid: sc for sid, sc in scene_scores.items() if sid in target}
        performer_scores = {}
        log.info(f"Restash: targeted write — {len(scene_scores)} of {len(target)} "
                 f"requested scene id(s) in corpus; performers skipped.")

    existing_scene_cf = {s.id: s.custom_fields for s in kept_scenes}
    existing_perf_cf = {p.id: p.custom_fields for p in kept_performers}
    s_stats = writer.write_scores(stash, "scene", scene_scores, existing_scene_cf,
                                  settings, now_iso)
    p_stats = writer.write_scores(stash, "performer", performer_scores, existing_perf_cf,
                                  settings, now_iso)
    log.progress(0.90)

    # D8: drop restash_* from entities now excluded but previously scored.
    # (Skipped entirely in targeted write mode — we touch only the named scenes.)
    if targeted:
        drop_scene_ids, drop_perf_ids = [], []
    else:
        drop_scene_ids = [s.id for s in scenes
                          if s.id not in kept_scene_ids and _has_restash(s.custom_fields)]
        drop_perf_ids = [p.id for p in performers
                         if p.id not in kept_perf_ids and _has_restash(p.custom_fields)]
    cleared = (writer.clear_scores(stash, "scene", drop_scene_ids, settings)
               + writer.clear_scores(stash, "performer", drop_perf_ids, settings))

    log.info(f"Restash full: scenes written={s_stats['written']} "
             f"skipped={s_stats['skipped']}; performers written={p_stats['written']} "
             f"skipped={p_stats['skipped']}; excluded cleared={cleared}.")
    s_failed, p_failed = s_stats.get("failed", 0), p_stats.get("failed", 0)
    if s_failed or p_failed:
        log.error(f"Restash: {s_failed} scene + {p_failed} performer update(s) were "
                  f"rejected by the server (those IDs were NOT written); re-run to retry.")
    clear_failed = (len(drop_scene_ids) + len(drop_perf_ids)) - cleared
    if clear_failed:
        log.error(f"Restash: {clear_failed} excluded-entity clear(s) were rejected by "
                  f"the server (restash_* keys remain on those IDs); re-run to retry.")
    if settings.write_limit and not targeted:
        log.info(f"Restash: write_limit={settings.write_limit} active — capped writes "
                 f"(scenes would_write={s_stats['would_write']}, "
                 f"performers would_write={p_stats['would_write']}).")
    log.progress(1.0)
    return 1 if (s_failed or p_failed or clear_failed) else 0


def _run_clear(stash, settings: config.Settings) -> int:
    log.progress(0.05)
    scenes = stash_io.fetch_scenes(stash)
    performers = stash_io.fetch_performers(stash)
    s_ids = [s.id for s in scenes if _has_restash(s.custom_fields)]
    p_ids = [p.id for p in performers if _has_restash(p.custom_fields)]
    log.progress(0.60)
    n = (writer.clear_scores(stash, "scene", s_ids, settings)
         + writer.clear_scores(stash, "performer", p_ids, settings))
    log.info(f"Restash clear: removed restash_* from {n} entities "
             f"({len(s_ids)} scenes, {len(p_ids)} performers). Other fields untouched.")
    failed = (len(s_ids) + len(p_ids)) - n
    if failed:
        log.error(f"Restash: {failed} clear(s) were rejected by the server "
                  f"(restash_* keys remain on those IDs); re-run to retry.")
    log.progress(1.0)
    return 1 if failed else 0


def _parse_cached_scenes(raw_scenes: dict) -> dict:
    """ISO strings → datetimes for the cached per-scene replay data."""
    out = {}
    for sid, c in raw_scenes.items():
        out[sid] = {
            "base": c["base"],
            "n_events": c["n_events"],
            "created_at": stash_io._parse_dt(c.get("created_at")) or stash_io.utcnow(),
            "last_engagement": stash_io._parse_dt(c.get("last_engagement")),
            "perf_ids": [str(x) for x in c.get("perf_ids", [])],
        }
    return out


def _scene_standins(corpus: dict, light_by_id: dict) -> list:
    """Lightweight SceneData stand-ins so score_performers can run unchanged:
    only the fields it reads are populated (performer_ids, play_count, created_at,
    last_played_at→computed last-engagement). Histories are empty so
    _last_engagement returns the computed anchor."""
    out = []
    for sid, c in corpus.items():
        cur = light_by_id[sid]
        last_eng = algorithm._max_dt(c.get("last_engagement"), cur.get("last_played_at"))
        out.append(models.SceneData(
            id=sid, title="", play_history=[], o_history=[],
            play_count=cur.get("play_count", 0), o_counter=cur.get("o_counter", 0),
            play_duration=0.0, resume_time=None, last_played_at=last_eng,
            file_duration=None, height=None, marker_count=0, organized=False,
            date=None, created_at=c["created_at"], rating100=None,
            tag_ids=[], performer_ids=c["perf_ids"], studio_id=None,
            custom_fields={}, has_file=True))
    return out


def _run_refresh(stash, settings: config.Settings) -> int:
    now = stash_io.utcnow()
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_seed = now.strftime("%Y-%m-%d")

    st = state.load_state(state.default_state_path())
    ok, reason = state.is_valid(st, settings)
    if not ok:
        log.info(f"Restash refresh: cache unusable ({reason}); running full recompute.")
        return _run_full(stash, settings)

    log.progress(0.10)
    light = stash_io.fetch_scenes_light(stash)
    light_by_id = {s["id"]: s for s in light}
    cached_scenes = _parse_cached_scenes(st["scenes"])
    corpus = {sid: c for sid, c in cached_scenes.items() if sid in light_by_id}
    added = [sid for sid in light_by_id if sid not in cached_scenes]
    dropped = [sid for sid in cached_scenes if sid not in light_by_id]
    log.info(f"Restash refresh: light-read {len(light)} scenes; cache has "
             f"{len(cached_scenes)}; scoring {len(corpus)}.")
    if added:
        log.info(f"Restash refresh: {len(added)} new scene(s) not in cache — they "
                 f"will be scored on the next full recompute.")
    if dropped:
        log.info(f"Restash refresh: {len(dropped)} cached scene(s) no longer in library.")
    log.progress(0.45)

    scene_scores = algorithm.refresh_scene_scores(corpus, light_by_id, settings,
                                                  now, date_seed)
    log.progress(0.65)

    performers = stash_io.fetch_performers(stash)
    aff = {"performers": st["affinities"].get("performers", {})}
    stand_ins = _scene_standins(corpus, light_by_id)
    performer_scores = algorithm.score_performers(performers, stand_ins, scene_scores,
                                                  aff, settings, now)
    log.progress(0.80)

    existing_scene_cf = {sid: light_by_id[sid]["custom_fields"] for sid in scene_scores}
    existing_perf_cf = {p.id: p.custom_fields for p in performers}
    s_stats = writer.write_scores(stash, "scene", scene_scores, existing_scene_cf,
                                  settings, now_iso)
    p_stats = writer.write_scores(stash, "performer", performer_scores, existing_perf_cf,
                                  settings, now_iso)
    log.progress(0.95)

    log.info(f"Restash refresh: scenes written={s_stats['written']} "
             f"skipped={s_stats['skipped']}; performers written={p_stats['written']} "
             f"skipped={p_stats['skipped']}.")
    s_failed, p_failed = s_stats.get("failed", 0), p_stats.get("failed", 0)
    if s_failed or p_failed:
        log.error(f"Restash: {s_failed} scene + {p_failed} performer update(s) were "
                  f"rejected by the server (those IDs were NOT written); re-run to retry.")
    log.progress(1.0)
    return 1 if (s_failed or p_failed) else 0


def _has_restash(custom_fields: dict) -> bool:
    return any(k in (custom_fields or {}) for k in writer.RESTASH_KEYS)


def _iso(dt) -> str | None:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _build_scene_cache(kept_scenes, scene_scores) -> dict:
    """Per-scene replay cache: pre-freshness base + the bits refresh needs."""
    out = {}
    for s in kept_scenes:
        sc = scene_scores.get(s.id)
        if sc is None:
            continue
        out[s.id] = {
            "base": sc.components.get("base"),
            "n_events": sc.n_events,
            "created_at": _iso(s.created_at),
            "last_engagement": _iso(algorithm._last_engagement(s)),
            "perf_ids": s.performer_ids,
        }
    return out


def _watched_diagnostic(scenes, scene_scores, settings, top_n: int = 20):
    """Gather read-only diagnostics for watched scenes (n_events>0): freshness,
    direct evidence, completion, and whether the abandonment penalty fired.
    Pure analysis over already-fetched data — no Stash calls, no writes."""
    rows = []
    penalty = penalty_high_comp = resume_zero = resume_zero_penalty = 0
    for s in scenes:
        sc = scene_scores.get(s.id)
        if sc is None or sc.n_events == 0:
            continue
        events = algorithm.extract_events(s, settings)
        fired = any(e.kind == "penalty" for e in events)
        comp = algorithm.completion_factor(s.play_duration, s.play_count,
                                           s.file_duration, settings.completion_floor)
        if fired:
            penalty += 1
            if comp >= 0.70:
                penalty_high_comp += 1
        if s.resume_time == 0.0:
            resume_zero += 1
            if fired:
                resume_zero_penalty += 1
        rows.append({
            "title": s.title or s.id, "score": sc.restash_score,
            "n_events": sc.n_events, "fresh": sc.components.get("fresh"),
            "fresh_d": sc.components.get("fresh_d"), "direct": sc.components.get("direct"),
            "confidence": sc.components.get("confidence"), "completion": comp,
            "resume_time": s.resume_time, "file_duration": s.file_duration,
            "penalty": fired, "play_count": s.play_count, "o_counter": s.o_counter,
        })
    rows.sort(key=lambda r: r["direct"] if r["direct"] is not None else 0.0,
              reverse=True)
    summary = {"watched": len(rows), "penalty": penalty,
               "penalty_high_completion": penalty_high_comp,
               "resume_zero": resume_zero, "resume_zero_penalty": resume_zero_penalty}
    return rows[:top_n], summary


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    return run(payload)


if __name__ == "__main__":
    sys.exit(main())
