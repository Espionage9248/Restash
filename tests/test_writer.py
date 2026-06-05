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

class _RecordingStash:
    def __init__(self):
        self.requests = []
    def call_GQL(self, query, variables=None):
        self.requests.append((query, variables))
        # mimic stashapi: return the data dict with one non-null alias per input
        return {f"u{k}": {"id": inp.get("id")}
                for k, inp in enumerate((variables or {}).values())}

def test_write_scores_skips_unchanged_and_batches():
    stash = _RecordingStash()
    scored = {"1": _ss("1", 80), "2": _ss("2", 90), "3": _ss("3", 70)}
    existing = {"1": {"restash_score": 80},        # unchanged → skip
                "2": {"restash_score": 5, "user_note": "keep"},  # changed → write
                "3": {}}                            # never scored → write
    cfg = Settings(write_chunk_size=10)
    stats = writer.write_scores(stash, "scene", scored, existing, cfg,
                                "2026-06-05T09:00:00Z")
    assert stats["skipped"] == 1
    assert stats["written"] == 2
    assert stats["failed"] == 0
    # one batched request for the 2 writes
    assert len(stash.requests) == 1
    # CRITICAL G3: every input uses custom_fields.partial, never .full
    _, variables = stash.requests[0]
    for inp in variables.values():
        assert "partial" in inp["custom_fields"]
        assert "full" not in inp["custom_fields"]

def test_write_scores_respects_chunk_size():
    stash = _RecordingStash()
    scored = {str(i): _ss(str(i), i % 100 + 1) for i in range(250)}
    cfg = Settings(write_chunk_size=100)
    stats = writer.write_scores(stash, "scene", scored, {}, cfg, "2026-06-05T09:00:00Z")
    assert stats["written"] == 250
    assert len(stash.requests) == 3   # 100 + 100 + 50

def test_write_scores_limit_caps_writes_for_subset_first():
    stash = _RecordingStash()
    scored = {str(i): _ss(str(i), i % 100 + 1) for i in range(50)}
    cfg = Settings(write_limit=5, write_chunk_size=100)
    stats = writer.write_scores(stash, "scene", scored, {}, cfg, "2026-06-05T09:00:00Z")
    assert stats["written"] == 5
    assert stats["would_write"] == 50

def test_clear_scores_uses_remove_with_restash_keys():
    stash = _RecordingStash()
    cfg = Settings(write_chunk_size=2)
    n = writer.clear_scores(stash, "scene", ["1", "2", "3"], cfg)
    assert n == 3
    assert len(stash.requests) == 2   # 2 + 1
    _, variables = stash.requests[0]
    for inp in variables.values():
        assert inp["custom_fields"]["remove"] == writer.RESTASH_KEYS
        assert "partial" not in inp["custom_fields"]
        assert "full" not in inp["custom_fields"]

def test_clear_scores_empty_is_noop():
    stash = _RecordingStash()
    assert writer.clear_scores(stash, "scene", [], Settings()) == 0
    assert stash.requests == []

def test_writer_source_has_no_full_or_rating100():
    # G3: the write layer must never use CustomFieldsInput.full or touch rating100.
    import pathlib
    src = pathlib.Path(writer.__file__).read_text()
    assert '"full"' not in src and "'full'" not in src
    assert "rating100" not in src


class _PartialFailStash:
    """Mimics stashapi returning HTTP200 + partial data: the aliases listed in
    null_indices come back null (their update errored), the rest succeed."""
    def __init__(self, null_indices):
        self.null_indices = set(null_indices)
        self.requests = []
    def call_GQL(self, query, variables=None):
        self.requests.append((query, variables))
        return {f"u{k}": (None if k in self.null_indices else {"id": "x"})
                for k in range(len(variables or {}))}

def test_count_succeeded_counts_non_null_aliases():
    assert writer._count_succeeded({"u0": {"id": "1"}, "u1": None, "u2": {"id": "3"}}, 3) == 2
    assert writer._count_succeeded({"u0": {"id": "1"}, "u1": {"id": "2"}}, 2) == 2
    # unrecognized / non-dict shape: assume all n succeeded (cannot prove failure)
    assert writer._count_succeeded(None, 4) == 4

def test_write_scores_counts_only_succeeded_aliases():
    stash = _PartialFailStash(null_indices=[1])   # 2nd update in the batch errors
    scored = {"1": _ss("1", 10), "2": _ss("2", 20), "3": _ss("3", 30)}
    cfg = Settings(write_chunk_size=10)
    stats = writer.write_scores(stash, "scene", scored, {}, cfg, "2026-06-06T00:00:00Z")
    assert stats["written"] == 2
    assert stats["failed"] == 1
    assert stats["would_write"] == 3

def test_clear_scores_counts_only_succeeded_aliases():
    stash = _PartialFailStash(null_indices=[0])   # 1st removal errors
    cfg = Settings(write_chunk_size=10)
    cleared = writer.clear_scores(stash, "scene", ["1", "2", "3"], cfg)
    assert cleared == 2
