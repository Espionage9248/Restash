import models
import report

def _ss(id, score, n=0, wild=False, **comp):
    return models.SceneScore(id=id, raw=comp.get("raw", 0.0), restash_score=score,
                             percentile=score / 100, n_events=n, wildcard=wild,
                             components={"base": 0.1, "ingredients": 0.2, "direct": 0.0,
                                         "confidence": 0.0, "fresh": 0.0,
                                         "novelty": 0.05, "jitter": 0.01, **comp})

def test_scene_report_lists_top_n_descending_with_terms():
    scores = {str(i): _ss(str(i), i) for i in range(1, 40)}
    titles = {str(i): f"Scene {i}" for i in range(1, 40)}
    text = report.format_scene_report(scores, titles, top_n=30)
    lines = [l for l in text.splitlines() if l.strip()]
    # header + 30 rows (at least)
    assert "Scene 39" in text and "Scene 9" not in text.split("Scene 10")[0]
    assert "base" in text and "novelty" in text   # itemized terms present
    assert text.index("Scene 39") < text.index("Scene 38")  # descending

def test_summary_counts_entities_and_would_writes():
    scores = {"a": _ss("a", 90), "b": _ss("b", 10)}
    s = report.format_summary(n_scenes=2, n_performers=0, would_write=2, skipped=0)
    assert "2" in s and "would" in s.lower()


def _ps(id, score, **comp):
    return models.PerformerScore(
        id=id, raw=comp.get("raw", 0.0), restash_score=score, percentile=score / 100,
        components={"scenes": 0.8, "affinity": 0.5, "fresh": 0.3, "supply": 0.2,
                    "novelty": 0.1, **comp})

def test_performer_report_descending_with_terms_and_name_fallback():
    scores = {"p1": _ps("p1", 40), "p2": _ps("p2", 95), "p3": _ps("p3", 70)}
    names = {"p1": "Alice", "p2": "Bdwoman"}   # p3 intentionally missing → falls back to id
    text = report.format_performer_report(scores, names, top_n=30)
    assert "=== TOP 30 PERFORMERS ===" in text
    # descending by restash_score: p2(95) before p3(70) before p1(40)
    assert text.index("Bdwoman") < text.index("p3") < text.index("Alice")
    # itemized perf terms present
    assert "scenes=" in text and "affinity=" in text and "supply=" in text
    # missing name falls back to id
    assert "p3" in text

def test_performer_report_respects_top_n():
    scores = {str(i): _ps(str(i), i) for i in range(1, 10)}
    text = report.format_performer_report(scores, {}, top_n=3)
    # only top 3 (scores 9,8,7) appear as score-prefixed rows
    assert "[  9]" in text and "[  8]" in text and "[  7]" in text
    assert "[  6]" not in text
