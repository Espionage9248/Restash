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

def test_aliased_mutation_uses_partial_not_full():
    q = writer.aliased_update_mutation("scene", 2)
    assert "sceneUpdate(input: $i0)" in q and "sceneUpdate(input: $i1)" in q
    assert "$i0: SceneUpdateInput!" in q and "$i1: SceneUpdateInput!" in q
    assert q.strip().startswith("mutation(")

def test_aliased_mutation_performer_type():
    q = writer.aliased_update_mutation("performer", 1)
    assert "performerUpdate(input: $i0)" in q
    assert "$i0: PerformerUpdateInput!" in q

def test_chunks_splits_evenly_and_remainder():
    assert list(writer._chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(writer._chunks([], 2)) == []

from config import Settings

class _FlakyStash:
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0
    def call_GQL(self, query, variables=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise Exception("503 Service Unavailable")
        return {"ok": True}

def test_call_with_retry_succeeds_after_transient_failures(monkeypatch):
    sleeps = []
    monkeypatch.setattr(writer.time, "sleep", lambda s: sleeps.append(s))
    stash = _FlakyStash(fail_times=2)
    cfg = Settings()   # max_retries=3, backoff_base=0.5
    assert writer._call_with_retry(stash, "q", {}, cfg) == {"ok": True}
    assert stash.calls == 3   # 2 failures + 1 success
    assert sleeps == [0.5, 1.0]   # backoff_base * 2^attempt before each retry

def test_call_with_retry_raises_after_exhausting(monkeypatch):
    sleeps = []
    monkeypatch.setattr(writer.time, "sleep", lambda s: sleeps.append(s))
    stash = _FlakyStash(fail_times=99)
    cfg = Settings()
    import pytest
    with pytest.raises(Exception, match="503 Service Unavailable"):  # last failure preserved
        writer._call_with_retry(stash, "q", {}, cfg)
    assert stash.calls == cfg.write_max_retries + 1   # initial + retries
    assert sleeps == [0.5, 1.0, 2.0]   # no sleep on the final (exhausting) attempt
