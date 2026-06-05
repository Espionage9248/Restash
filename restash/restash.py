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
    print(report.format_summary(len(scene_scores), len(performer_scores),
                                would_write=len(scene_scores) + len(performer_scores),
                                skipped=0))
    log.progress(1.0)
    return 0


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    return run(payload)


if __name__ == "__main__":
    sys.exit(main())
