import config

def test_defaults_match_spec():
    s = config.Settings()
    assert s.taste_half_life_days == 90.0
    assert s.cooldown_days == 21.0
    assert s.wildcard_percent == 2.0
    assert s.exclude_tag_name == "[Restash: Exclude]"
    assert s.mirror_to_rating100 is False

def test_from_plugin_settings_overrides_defaults():
    # plugin settings use the restash.yml camelCase keys
    plugin_cfg = {"tasteHalfLifeDays": 45, "cooldownDays": 10, "mirrorToRating100": True}
    s = config.Settings.from_plugin_settings(plugin_cfg)
    assert s.taste_half_life_days == 45.0
    assert s.cooldown_days == 10.0
    assert s.mirror_to_rating100 is True
    # untouched key keeps default
    assert s.wildcard_percent == 2.0

def test_from_plugin_settings_ignores_unknown_keys():
    s = config.Settings.from_plugin_settings({"somethingElse": 7})
    assert s == config.Settings()

def test_write_settings_defaults():
    s = config.Settings()
    assert s.write_chunk_size == 100
    assert s.write_max_retries == 3
    assert s.write_backoff_base == 0.5
    assert s.write_limit == 0   # 0 = write all; >0 caps (subset-first gate)

def test_write_only_scene_ids_default_empty():
    assert config.Settings().write_only_scene_ids == ()
