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
