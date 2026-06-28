from googledrive_sync import config


def test_state_roundtrip(tmp_path):
    sf = tmp_path / "googledrive.yml"
    state = config.State(state_file=sf)
    assert state.last_sync_epoch == 0
    assert state.remote_pathfiles == []

    state.last_sync_epoch = 12345
    state.remote_pathfiles = ["/b.txt", "/a.txt"]
    state.save()

    reloaded = config.State(state_file=sf)
    assert reloaded.last_sync_epoch == 12345
    # stored sorted
    assert reloaded.remote_pathfiles == ["/a.txt", "/b.txt"]


def test_state_handles_string_epoch(tmp_path):
    sf = tmp_path / "googledrive.yml"
    config.dump_yaml(sf, {"last_sync_epoch": "1781601064"})
    state = config.State(state_file=sf)
    assert state.last_sync_epoch == 1781601064


def test_load_yaml_missing(tmp_path):
    assert config.load_yaml(tmp_path / "nope.yml") == {}
