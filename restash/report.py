from __future__ import annotations
import models

_SCENE_TERMS = ["base", "ingredients", "perf", "tag", "studio", "quality",
                "direct", "confidence", "fresh", "fresh_d", "novelty", "jitter"]
_PERF_TERMS = ["scenes", "affinity", "fresh", "supply", "novelty"]


def _fmt_terms(components: dict, keys: list[str]) -> str:
    parts = []
    for k in keys:
        v = components.get(k)
        if v is None:
            continue
        parts.append(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}")
    return " ".join(parts)


def format_scene_report(scores: dict[str, models.SceneScore],
                        titles: dict[str, str], top_n: int = 30) -> str:
    ranked = sorted(scores.values(), key=lambda s: s.restash_score, reverse=True)
    lines = [f"=== TOP {top_n} SCENES ==="]
    for s in ranked[:top_n]:
        wild = " [WILDCARD]" if s.wildcard else ""
        title = titles.get(s.id, s.id)
        lines.append(f"[{s.restash_score:3d}] {title}{wild} "
                     f"(raw={s.raw:.3f}, n_events={s.n_events})")
        lines.append(f"        {_fmt_terms(s.components, _SCENE_TERMS)}")
    return "\n".join(lines)


def format_performer_report(scores: dict[str, models.PerformerScore],
                            names: dict[str, str], top_n: int = 30) -> str:
    ranked = sorted(scores.values(), key=lambda p: p.restash_score, reverse=True)
    lines = [f"=== TOP {top_n} PERFORMERS ==="]
    for p in ranked[:top_n]:
        name = names.get(p.id, p.id)
        lines.append(f"[{p.restash_score:3d}] {name} (raw={p.raw:.3f})")
        lines.append(f"        {_fmt_terms(p.components, _PERF_TERMS)}")
    return "\n".join(lines)


def format_watched_diagnostic(rows: list[dict], summary: dict,
                              top_n: int = 20) -> str:
    """Read-only tuning diagnostic: how watched scenes (n_events>0) are scored,
    and whether the abandonment penalty is firing on high-completion scenes
    (the 'Stash reset resume_time to 0 after a full watch' signature)."""
    lines = ["=== WATCHED-SCENE DIAGNOSTIC (scenes with play/o history) ==="]
    lines.append(f"watched scenes (n_events>0): {summary['watched']}")
    lines.append(f"abandonment penalty fired on: {summary['penalty']} scenes")
    lines.append(f"  ...of which completion >= 0.70 "
                 f"(SUSPICIOUS — watched a lot but penalized): "
                 f"{summary['penalty_high_completion']}")
    lines.append(f"scenes with resume_time == 0.0 exactly: {summary['resume_zero']}")
    lines.append(f"  ...of which the penalty also fired "
                 f"(the 'reset-to-0-after-watch' signature): "
                 f"{summary['resume_zero_penalty']}")
    lines.append(f"--- TOP {top_n} WATCHED SCENES (by direct evidence) ---")
    for r in rows:
        pen = "YES" if r["penalty"] else "no"
        fresh_d = r["fresh_d"]
        fresh_d_s = f"{fresh_d:.1f}" if isinstance(fresh_d, float) else str(fresh_d)
        resume = r["resume_time"]
        resume_s = f"{resume:.1f}" if isinstance(resume, float) else str(resume)
        dur = r["file_duration"]
        dur_s = f"{dur:.0f}" if isinstance(dur, float) else str(dur)
        lines.append(f"[{r['score']:3d}] {r['title']} "
                     f"(plays={r['play_count']}, o={r['o_counter']}, "
                     f"n_events={r['n_events']})")
        lines.append(f"        fresh={r['fresh']:.3f} fresh_d={fresh_d_s} "
                     f"direct={r['direct']:.3f} confidence={r['confidence']:.3f} "
                     f"completion={r['completion']:.2f} "
                     f"resume={resume_s}/{dur_s} penalty={pen}")
    return "\n".join(lines)


def format_summary(n_scenes: int, n_performers: int, would_write: int,
                   skipped: int) -> str:
    return ("=== DRY RUN SUMMARY ===\n"
            f"scenes scored: {n_scenes}\n"
            f"performers scored: {n_performers}\n"
            f"writes that WOULD occur: {would_write}\n"
            f"writes that would be skipped (unchanged): {skipped}\n"
            "(dry run — nothing was written)")
