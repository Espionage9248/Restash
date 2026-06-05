#!/usr/bin/env python3
"""Offline warm-up & scale simulation for Restash scoring (NO Stash connection).

Generates synthetic libraries with a controllable watch-history density and size,
runs the REAL pure scoring algorithm, and reports how the feed behaves as watch
history accumulates and as the library grows. Pure/offline — imports only the
flat plugin modules; never touches the network.

Usage:  python restash/tools/simulate.py
"""
from __future__ import annotations
import random
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # restash/
import algorithm  # noqa: E402
import models  # noqa: E402
from config import Settings  # noqa: E402

NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)


def _wsample_no_replace(rng, items, weights, k):
    """Weighted sample without replacement (Efraimidis–Spirakis A-Res)."""
    keyed = ((rng.random() ** (1.0 / max(w, 1e-9)), it) for it, w in zip(items, weights))
    return [it for _, it in sorted(keyed, key=lambda x: x[0], reverse=True)[:k]]


def make_library(n_scenes, watched_frac, rng, now=NOW, n_tags=200, n_studios=40):
    """Synthesize a library where the user's WATCHES correlate with a hidden taste
    (so the affinity model has real signal to learn), with a realistic mix of recent
    and long-dormant watches to exercise the cooldown/rediscovery curve."""
    n_perf = max(50, n_scenes // 3)
    perf, tags, studios = ([f"p{i}" for i in range(n_perf)],
                           [f"t{i}" for i in range(n_tags)],
                           [f"st{i}" for i in range(n_studios)])
    # hidden appeal (what the user likes), skewed: a few loved, many meh
    appeal = {x: rng.betavariate(2, 5) for x in perf + tags + studios}
    # popularity (how often they appear) — Zipf-ish, independent of appeal
    perf_pop = [1.0 / (i + 1) for i in range(n_perf)]
    studio_pop = [1.0 / (i + 1) for i in range(n_studios)]

    scenes, scene_appeal = [], {}
    for i in range(n_scenes):
        sid = f"s{i}"
        kp = rng.choices([1, 2, 3, 4], weights=[5, 4, 2, 1])[0]
        perfs = list(dict.fromkeys(rng.choices(perf, weights=perf_pop, k=kp)))
        tg = rng.sample(tags, rng.randint(2, 6))
        st = rng.choices(studios, weights=studio_pop)[0]
        dur = rng.uniform(600, 3600)
        scene_appeal[sid] = (sum(appeal[p] for p in perfs) / len(perfs) * 0.5
                             + sum(appeal[t] for t in tg) / len(tg) * 0.3
                             + appeal[st] * 0.2)
        scenes.append(models.SceneData(
            id=sid, title=sid, play_history=[], o_history=[], play_count=0,
            o_counter=0, play_duration=0.0, resume_time=None, last_played_at=None,
            file_duration=dur, height=rng.choice([480, 720, 1080, 1080, 1080, 2160]),
            marker_count=rng.randint(0, 12), organized=rng.random() < 0.3, date=None,
            created_at=now - timedelta(days=rng.uniform(1, 1000)), rating100=None,
            tag_ids=tg, performer_ids=perfs, studio_id=st, custom_fields={},
            has_file=True))

    watched = _wsample_no_replace(rng, scenes, [scene_appeal[s.id] for s in scenes],
                                  int(n_scenes * watched_frac))
    recent_ids, dormant_ids = set(), set()
    for s in watched:
        last_days = rng.uniform(0, 300)
        s.play_count = rng.randint(1, 3)
        comp = min(1.0, 0.3 + scene_appeal[s.id])           # liked → watched more
        s.play_duration = s.play_count * s.file_duration * comp
        s.play_history = [now - timedelta(days=last_days + rng.uniform(0, 20))
                          for _ in range(s.play_count)]
        last_play = max(s.play_history)
        s.last_played_at = last_play
        n_o = rng.choices([0, 1, 2], weights=[1, 1 + scene_appeal[s.id],
                                              scene_appeal[s.id]])[0]
        s.o_counter = n_o
        s.o_history = [last_play - timedelta(days=rng.uniform(0, 5)) for _ in range(n_o)]
        s.resume_time = 0.0 if comp > 0.9 else rng.uniform(0, 0.3) * s.file_duration
        if last_days < 21:
            recent_ids.add(s.id)        # in cooldown — should be buried
        elif last_days > 90:
            dormant_ids.add(s.id)       # in rediscovery — should be lifted
    return scenes, {s.id for s in watched}, recent_ids, dormant_ids


def _median(xs):
    return statistics.median(xs) if xs else float("nan")


def _pct_watched_top(ss, watched_ids, top_n):
    ranked = sorted(ss.values(), key=lambda s: s.restash_score, reverse=True)[:top_n]
    return 100.0 * sum(1 for s in ranked if s.id in watched_ids) / max(1, len(ranked))


def warmup_sweep():
    cfg = Settings()
    print("=== WARM-UP: how watch-history density reshapes the feed (N=5000) ===")
    print(f"{'watched%':>9} {'#watched':>9} {'top30':>8} {'top100':>8} "
          f"{'recent':>8} {'dormant':>8} {'unwatch':>8}")
    for frac in (0.005, 0.02, 0.10, 0.30):
        rng = random.Random(42)
        scenes, watched_ids, recent_ids, dormant_ids = make_library(5000, frac, rng)
        ss = algorithm.score_scenes(scenes, cfg, NOW, "2026-06-05")
        recent_med = _median([ss[i].restash_score for i in recent_ids])
        dormant_med = _median([ss[i].restash_score for i in dormant_ids])
        unwatched_med = _median([s.restash_score for s in ss.values()
                                 if s.id not in watched_ids])
        print(f"{frac*100:>8.1f}% {len(watched_ids):>9} "
              f"{_pct_watched_top(ss, watched_ids, 30):>7.0f}% "
              f"{_pct_watched_top(ss, watched_ids, 100):>7.0f}% "
              f"{recent_med:>8.0f} {dormant_med:>8.0f} {unwatched_med:>8.0f}")
    print("\n  top30/top100 = % of the top scenes that you've actually watched")
    print("  recent  = median score of scenes watched <21 days ago (cooldown buries)")
    print("  dormant = median score of scenes watched >90 days ago (rediscovery lifts)")
    print("  unwatch = median score of never-watched scenes (baseline)")
    print("  → cooldown works when recent < dormant; warm-up shows top% climbing.")


def scale_test():
    cfg = Settings()
    print("\n=== SCALE: scoring time + score distribution at large N (5% watched) ===")
    print(f"{'N scenes':>9} {'time':>8} {'span':>10} {'distinct':>9} {'median':>7}")
    for n in (5000, 20000, 50000):
        rng = random.Random(7)
        scenes, _, _, _ = make_library(n, 0.05, rng)
        t0 = time.perf_counter()
        aff = algorithm.build_affinities(scenes, NOW, cfg, set(), {})
        ss = algorithm.score_scenes(scenes, cfg, NOW, "2026-06-05", aff=aff)
        dt = time.perf_counter() - t0
        sc = sorted(s.restash_score for s in ss.values())
        print(f"{n:>9} {dt:>7.1f}s {f'{sc[0]}-{sc[-1]}':>10} "
              f"{len(set(sc)):>9} {sc[len(sc)//2]:>7}")
    print("\n  span/distinct = the 1–100 percentile spread stays smooth at scale")
    print("  (scoring is in-memory CPU; the spec's <60s target is for the network read)")


def cooldown_curve():
    """Isolate the mechanism: ONE scene, fixed evidence (1 play + 1 o), swept across
    days-since-watch. Shows how taste-decay (base falls) and the freshness curve
    (rises) interact — i.e. whether a long-dormant favourite actually resurfaces."""
    cfg = Settings()
    aff = {"performers": {"p0": 0.6}, "tags": {}, "studios": {}}
    print("\n=== COOLDOWN/REDISCOVERY: one scene, fixed evidence, vary days-since-watch ===")
    print(f"{'days ago':>9} {'base':>7} {'fresh':>7} {'final':>7}")
    for days in (0, 1, 5, 14, 21, 45, 90, 150, 250, 365):
        s = models.SceneData(
            id="x", title="x", play_history=[NOW - timedelta(days=days)],
            o_history=[NOW - timedelta(days=days)], play_count=1, o_counter=1,
            play_duration=1500.0, resume_time=1400.0,
            last_played_at=NOW - timedelta(days=days), file_duration=1500.0,
            height=1080, marker_count=0, organized=False, date=None,
            created_at=NOW - timedelta(days=500), rating100=None, tag_ids=[],
            performer_ids=["p0"], studio_id=None, custom_fields={}, has_file=True)
        comp = algorithm.scene_base(s, aff, {}, None, None, cfg, NOW)
        f = algorithm.freshness(days, cfg)
        final = comp["base"] + f * abs(comp["base"]) * cfg.fresh_weight
        print(f"{days:>9} {comp['base']:>7.3f} {f:>7.3f} {final:>7.3f}")
    print("  base = strength of (decaying) evidence; fresh = cooldown→rediscovery curve;")
    print("  final = base + fresh*|base|. If 'final' doesn't recover at high days, the")
    print("  90-day taste-decay is eroding rediscovery faster than the curve restores it.")


if __name__ == "__main__":
    warmup_sweep()
    cooldown_curve()
    scale_test()
