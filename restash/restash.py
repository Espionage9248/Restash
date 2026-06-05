from __future__ import annotations
import json
import sys

import algorithm
import config
import report
import stash_io
import writer
from stashapi import log   # stashapp-tools logging → drives Stash progress bar


def parse_input(payload: dict):
    args = payload.get("args") or {}
    mode = args.get("mode") or "dry"
    conn = payload.get("server_connection") or {}
    plugin_cfg = payload.get("plugin_config") or args
    settings = config.Settings.from_plugin_settings(plugin_cfg)
    if "write_limit" in args:
        settings.write_limit = int(args["write_limit"])
    if "scene_ids" in args:
        settings.write_only_scene_ids = tuple(str(i) for i in args["scene_ids"])
    return mode, conn, settings


def run(payload: dict) -> int:
    mode, conn, settings = parse_input(payload)
    stash = stash_io.connect(conn)
    caps = stash_io.ensure_schema(stash)
    log.info(f"Restash: schema OK (scene custom_fields, "
             f"remove={caps['custom_fields_remove']}). mode={mode}")
    if mode == "dry":
        return _run_dry(stash, settings)
    if mode == "full":
        return _run_full(stash, settings)
    if mode == "clear":
        return _run_clear(stash, settings)
    if mode == "refresh":
        log.info("Restash: 'refresh' is not implemented in this build (Phase 6).")
        return 0
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
    print(report.format_scene_report(scene_scores, titles, top_n=30))
    print(report.format_performer_report(performer_scores, names, top_n=30))
    diag_rows, diag_summary = _watched_diagnostic(scenes, scene_scores, settings)
    print(report.format_watched_diagnostic(diag_rows, diag_summary, top_n=20))
    print(report.format_summary(len(scene_scores), len(performer_scores),
                                would_write=len(scene_scores) + len(performer_scores),
                                skipped=0))
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


def _has_restash(custom_fields: dict) -> bool:
    return any(k in (custom_fields or {}) for k in writer.RESTASH_KEYS)


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
