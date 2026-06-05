import json
import models
import writer

def _ss(id="1", score=87):
    return models.SceneScore(id=id, raw=1.4234, restash_score=score, percentile=0.87,
                             n_events=3, wildcard=False,
                             components={"base": 0.12345, "fresh": -0.9, "jitter": 0.01})

def _ps(id="9", score=72):
    return models.PerformerScore(id=id, raw=0.6611, restash_score=score, percentile=0.72,
                                 components={"scenes": 0.8, "affinity": 0.5})

def test_scene_partial_has_all_keys_and_types():
    p = writer.scene_partial(_ss(), "2026-06-05T09:00:00Z")
    assert set(p) == set(writer.RESTASH_KEYS)
    assert p["restash_score"] == 87 and isinstance(p["restash_score"], int)
    assert p["restash_raw"] == 1.4234
    assert json.loads(p["restash_components"])["base"] == 0.123   # rounded
    assert p["restash_updated"] == "2026-06-05T09:00:00Z"

def test_performer_partial_has_all_keys():
    p = writer.performer_partial(_ps(), "2026-06-05T09:00:00Z")
    assert set(p) == set(writer.RESTASH_KEYS)
    assert p["restash_score"] == 72

def test_needs_write_skips_when_score_unchanged():
    new = writer.scene_partial(_ss(score=50), "2026-06-05T09:00:00Z")
    assert writer.needs_write({"restash_score": 50}, new) is False     # int match
    assert writer.needs_write({"restash_score": "50"}, new) is False   # string match
    assert writer.needs_write({"restash_score": 49}, new) is True      # changed
    assert writer.needs_write({}, new) is True                         # never scored
    assert writer.needs_write({"foo": "bar"}, new) is True             # only foreign keys
