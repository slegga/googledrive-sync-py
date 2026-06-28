import os
import time

import pytest

from fake_backend import FakeDriveBackend
from googledrive_sync import config
from googledrive_sync.mirror import Mirror


@pytest.fixture
def env(tmp_path, monkeypatch):
    local_root = tmp_path / "local"
    local_root.mkdir()
    monkeypatch.setattr(config, "BACKUP_ROOT", tmp_path / "backup")
    monkeypatch.setattr(config, "CONFLICT_REMOVED_ROOT", tmp_path / "removed")
    state = config.State(state_file=tmp_path / "state.yml")
    backend = FakeDriveBackend()
    mirror = Mirror(backend, local_root=local_root, state=state)
    return mirror, backend, local_root, tmp_path


def write_local(local_root, rel, content, mtime=None):
    path = local_root / rel.lstrip("/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_upload_local_only(env):
    mirror, backend, local_root, _ = env
    write_local(local_root, "/notes.txt", b"local-content")
    plan = mirror.sync()
    assert plan["upload"] == ["/notes.txt"]
    assert plan["download"] == []
    # exists remotely now
    found = backend.find_files("notes.txt", "root")
    assert len(found) == 1
    assert backend.download(found[0]["id"]) == b"local-content"


def test_download_remote_only(env):
    mirror, backend, local_root, _ = env
    backend.add_file("remote.txt", "root", b"remote-content")
    plan = mirror.sync()
    assert plan["download"] == ["/remote.txt"]
    assert plan["upload"] == []
    assert (local_root / "remote.txt").read_bytes() == b"remote-content"


def test_in_sync_no_changes(env):
    mirror, backend, local_root, _ = env
    backend.add_file("same.txt", "root", b"same")
    write_local(local_root, "/same.txt", b"same")
    plan = mirror.sync()
    assert plan["download"] == []
    assert plan["upload"] == []


def test_conflict_cloud_wins(env):
    mirror, backend, local_root, _ = env
    # remote modified "now", local file older with different content
    backend.add_file("c.txt", "root", b"REMOTE-NEW")
    write_local(local_root, "/c.txt", b"local-old", mtime=time.time() - 3600)
    plan = mirror.sync()
    assert "/c.txt" in plan["download"]
    assert (local_root / "c.txt").read_bytes() == b"REMOTE-NEW"


def test_remote_deletion_archived(env):
    mirror, backend, local_root, tmp_path = env
    # First sync records the remote file.
    fid = backend.add_file("gone.txt", "root", b"data")
    mirror.sync()
    assert (local_root / "gone.txt").exists()
    # Remove on remote; next sync should archive the local copy.
    backend.delete(fid)
    plan = mirror.sync()
    assert plan["deleted"] == ["/gone.txt"]
    assert not (local_root / "gone.txt").exists()
    assert (tmp_path / "removed" / "gone.txt").read_bytes() == b"data"


def test_dry_run_does_nothing(env):
    mirror, backend, local_root, _ = env
    write_local(local_root, "/x.txt", b"x")
    plan = mirror.sync(dry_run=True)
    assert plan["upload"] == ["/x.txt"]
    # nothing uploaded
    assert backend.find_files("x.txt", "root") == []


def test_is_needing_sync(env):
    mirror, backend, local_root, _ = env
    assert mirror.is_needing_sync() is False
    write_local(local_root, "/new.txt", b"new")
    assert mirror.is_needing_sync() is True


def test_nested_paths(env):
    mirror, backend, local_root, _ = env
    sub = backend.add_folder("dir", "root")
    backend.add_folder("deep", sub)
    deep_id = backend.find_files("deep", sub)[0]["id"]
    backend.add_file("r.txt", deep_id, b"deep-remote")
    write_local(local_root, "/dir/local.txt", b"deep-local")
    plan = mirror.sync()
    assert "/dir/deep/r.txt" in plan["download"]
    assert "/dir/local.txt" in plan["upload"]
    assert (local_root / "dir" / "deep" / "r.txt").read_bytes() == b"deep-remote"


def test_clean_remote_duplicates(env):
    mirror, backend, local_root, _ = env
    backend.add_file("dup.txt", "root", b"same", modified="2020-01-01T00:00:00.000Z")
    backend.add_file("dup.txt", "root", b"same", modified="2021-01-01T00:00:00.000Z")
    backend.add_file("empty.txt", "root", b"")
    mirror.clean_remote_duplicates()
    remaining = [f["name"] for f in backend.list_all_files()]
    # one dup kept, empty removed
    assert remaining.count("dup.txt") == 1
    assert "empty.txt" not in remaining


def test_ignores_ds_store_local(env):
    mirror, backend, local_root, _ = env
    write_local(local_root, "/.DS_Store", b"junk")
    write_local(local_root, "/keep.txt", b"keep")
    assert mirror.is_needing_sync() is True  # keep.txt triggers it
    plan = mirror.sync()
    assert plan["upload"] == ["/keep.txt"]
    assert backend.find_files(".DS_Store", "root") == []


def test_ds_store_alone_no_sync(env):
    mirror, backend, local_root, _ = env
    write_local(local_root, "/.DS_Store", b"junk")
    assert mirror.is_needing_sync() is False


def test_ignores_remote_ds_store(env):
    mirror, backend, local_root, _ = env
    backend.add_file(".DS_Store", "root", b"junk")
    plan = mirror.sync()
    assert plan["download"] == []
    assert not (local_root / ".DS_Store").exists()
