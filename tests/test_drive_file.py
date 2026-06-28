import pytest

from fake_backend import FakeDriveBackend
from googledrive_sync.drive_file import DriveFile


def make_file(backend, pathfile, tmp_path):
    return DriveFile(
        backend,
        pathfile,
        local_root=tmp_path / "local",
        backup_root=tmp_path / "backup",
    )


def test_lfile_and_name(tmp_path):
    backend = FakeDriveBackend()
    f = make_file(backend, "/dir/file.txt", tmp_path)
    assert f.name == "file.txt"
    assert f.lfile == tmp_path / "local" / "dir" / "file.txt"
    assert f.parts == ["dir", "file.txt"]


def test_mime_type(tmp_path):
    backend = FakeDriveBackend()
    f = make_file(backend, "/a.txt", tmp_path)
    assert f.file_mime_type() == "text/plain"
    f2 = make_file(backend, "/a.unknownext", tmp_path)
    assert f2.file_mime_type() == "application/octet-stream"


def test_get_metadata_resolves_nested(tmp_path):
    backend = FakeDriveBackend()
    sub = backend.add_folder("dir", "root")
    fid = backend.add_file("file.txt", sub, b"hello")
    f = make_file(backend, "/dir/file.txt", tmp_path)
    meta = f.get_metadata()
    assert meta["id"] == fid


def test_get_metadata_missing_returns_none(tmp_path):
    backend = FakeDriveBackend()
    f = make_file(backend, "/dir/ghost.txt", tmp_path)
    assert f.get_metadata() is None


def test_path_resolve(tmp_path):
    backend = FakeDriveBackend()
    sub = backend.add_folder("dir", "root")
    backend.add_file("file.txt", sub, b"x")
    f = make_file(backend, "/dir/file.txt", tmp_path)
    resolved = f.path_resolve()
    # root, dir, file
    assert len(resolved) == 3
    assert resolved[0]["id"] == "root"
    assert resolved[1]["name"] == "dir"
    assert resolved[2]["name"] == "file.txt"


def test_upload_new_creates_folders(tmp_path):
    backend = FakeDriveBackend()
    local = tmp_path / "local" / "newdir"
    local.mkdir(parents=True)
    (local / "f.txt").write_bytes(b"content")
    f = make_file(backend, "/newdir/f.txt", tmp_path)
    f.upload()
    # the file now exists remotely under a created folder
    found = make_file(backend, "/newdir/f.txt", tmp_path).get_metadata()
    assert found is not None
    assert backend.download(found["id"]) == b"content"


def test_download_writes_local_with_backup(tmp_path):
    backend = FakeDriveBackend()
    sub = backend.add_folder("dir", "root")
    backend.add_file("file.txt", sub, b"remote-data")
    f = make_file(backend, "/dir/file.txt", tmp_path)
    # pre-existing local file should be backed up
    f.lfile.parent.mkdir(parents=True)
    f.lfile.write_bytes(b"old-local")
    f.download()
    assert f.lfile.read_bytes() == b"remote-data"
    assert f.backup_file.read_bytes() == b"old-local"


def test_remove_local_and_remote(tmp_path):
    backend = FakeDriveBackend()
    sub = backend.add_folder("dir", "root")
    fid = backend.add_file("file.txt", sub, b"data")
    f = make_file(backend, "/dir/file.txt", tmp_path)
    f.lfile.parent.mkdir(parents=True)
    f.lfile.write_bytes(b"data")
    f.remove()
    assert not f.lfile.exists()
    assert fid not in backend.files
    assert "Removed remote file" in f.last_message
