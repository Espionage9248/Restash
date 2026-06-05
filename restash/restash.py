from __future__ import annotations
import json
import sys

import algorithm
import config
import report
import stash_io
from stashapi import log   # stashapp-tools logging → drives Stash progress bar


def parse_input(payload: dict):
    args = payload.get("args") or {}
    mode = args.get("mode") or "dry"
    conn = payload.get("server_connection") or {}
    plugin_cfg = payload.get("plugin_config") or args
    settings = config.Settings.from_plugin_settings(plugin_cfg)
    return mode, conn, settings


def run(payload: dict) -> int:
    mode, conn, settings = parse_input(payload)
    stash = stash_io.connect(conn)
    caps = stash_io.ensure_schema(stash)
    log.info(f"Restash: schema OK (scene custom_fields, "
             f"remove={caps['custom_fields_remove']}). mode={mode}")
    if mode == "dry":
        return _run_dry(stash, settings)
    if mode in ("full", "refresh", "clear"):
        log.info(f"Restash: mode '{mode}' is not implemented in this build "
                 f"(dry-run-only). Nothing written.")
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
