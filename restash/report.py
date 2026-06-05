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


def format_summary(n_scenes: int, n_performers: int, would_write: int,
                   skipped: int) -> str:
    return ("=== DRY RUN SUMMARY ===\n"
            f"scenes scored: {n_scenes}\n"
            f"performers scored: {n_performers}\n"
            f"writes that WOULD occur: {would_write}\n"
            f"writes that would be skipped (unchanged): {skipped}\n"
            "(dry run — nothing was written)")
