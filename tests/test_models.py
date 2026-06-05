from datetime import datetime, timezone
import models

def test_scenedata_constructs_with_minimal_fields():
    s = models.SceneData(
        id="1", title="x", play_history=[], o_history=[], play_count=0,
        o_counter=0, play_duration=0.0, resume_time=None, last_played_at=None,
        file_duration=None, height=None, marker_count=0, organized=False,
        date=None, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rating100=None, tag_ids=[], performer_ids=[], studio_id=None,
        custom_fields={}, has_file=False)
    assert s.id == "1"
    assert s.has_file is False

def test_scorecontainers_default_components():
    sc = models.SceneScore(id="1", raw=0.0, restash_score=1, percentile=0.0,
                           n_events=0, wildcard=False, components={})
    assert sc.components == {}
    ps = models.PerformerScore(id="9", raw=0.0, restash_score=1,
                               percentile=0.0, components={})
    assert ps.restash_score == 1
