"""Two-way mirror between a local directory and Google Drive.

Python rewrite of ``Mojo::GoogleDrive::Mirror``. The sync algorithm is kept
faithful to the original: on conflicting changes the cloud copy wins.
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .backend import DriveBackend, FOLDER_MIME, GOOGLE_APPS_PREFIX
from .drive_file import DriveFile, _md5_hex


def parse_rfc3339(value: str) -> float:
    """Parse a Drive RFC3339 timestamp into a unix epoch (float)."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).timestamp()


class Mirror:
    """Container for config/credentials and the sync engine."""

    def __init__(
        self,
        backend: DriveBackend,
        *,
        local_root: Path = config.DEFAULT_LOCAL_ROOT,
        remote_root: str = "/",
        state: Optional[config.State] = None,
        debug: bool = False,
        ignore=None,
    ):
        self.backend = backend
        self.local_root = Path(local_root)
        self.remote_root = remote_root
        self.state = state if state is not None else config.State()
        self.debug = debug
        self.ignore = config.DEFAULT_IGNORE if ignore is None else ignore

    # -- factory -----------------------------------------------------------

    def file(self, pathfile: str) -> DriveFile:
        return DriveFile(
            self.backend,
            pathfile,
            local_root=self.local_root,
            backup_root=config.BACKUP_ROOT,
            debug=self.debug,
        )

    def _log(self, *args) -> None:
        if self.debug:
            print(*args)

    # -- local scanning ----------------------------------------------------

    def _local_files(self) -> Dict[str, Dict]:
        """Map remote-relative pathfile -> {md5, modifiedTime, size}."""
        out: Dict[str, Dict] = {}
        root = self.local_root
        if not root.exists():
            return out
        for dirpath, _dirs, filenames in os.walk(root):
            for fname in filenames:
                full = Path(dirpath) / fname
                if not full.is_file():
                    continue
                rel = "/" + full.relative_to(root).as_posix()
                if config.is_ignored(rel, self.ignore):
                    continue
                st = full.stat()
                out[rel] = {
                    "md5Checksum": _md5_hex(full),
                    "modifiedTime": st.st_mtime,
                    "size": st.st_size,
                }
        return out

    def _newest_local_mtime(self) -> float:
        newest = 0.0
        root = self.local_root
        if not root.exists():
            return newest
        for dirpath, _dirs, filenames in os.walk(root):
            for fname in filenames:
                full = Path(dirpath) / fname
                rel = "/" + full.relative_to(root).as_posix()
                if config.is_ignored(rel, self.ignore):
                    continue
                try:
                    st = full.stat()
                except OSError:
                    continue
                newest = max(newest, st.st_mtime, st.st_ctime)
        return newest

    # -- remote scanning ---------------------------------------------------

    def _build_id_to_pathfile(self, folders: List[Dict], root_id: str) -> Dict[str, str]:
        """Resolve folder ids to their full ``/a/b`` pathfile."""
        id2path = {root_id: ""}
        remaining = [dict(f) for f in folders]
        # Repeatedly attach folders whose parent is already resolved.
        for _ in range(len(remaining) + 1):
            progressed = False
            for folder in remaining:
                if folder is None or folder["id"] in id2path:
                    continue
                parents = folder.get("parents") or []
                if parents and parents[0] in id2path:
                    id2path[folder["id"]] = id2path[parents[0]] + "/" + folder["name"]
                    progressed = True
            if not progressed:
                break
        return id2path

    def _remote_files(self, since_epoch: Optional[int]) -> List[Dict]:
        """Return remote files annotated with a ``pathfile`` key."""
        root = self.backend.get_root()
        folders = self.backend.list_folders()
        id2path = self._build_id_to_pathfile(folders, root["id"])

        files = self.backend.list_changed_files(since_epoch)
        annotated = []
        for f in files:
            parents = f.get("parents") or []
            if not parents or parents[0] not in id2path:
                continue  # shared-with-me or orphaned; skip
            f = dict(f)
            f["pathfile"] = id2path[parents[0]] + "/" + f["name"]
            if config.is_ignored(f["pathfile"], self.ignore):
                continue
            f["_mtime_epoch"] = (
                parse_rfc3339(f["modifiedTime"]) if f.get("modifiedTime") else 0.0
            )
            annotated.append(f)
        return annotated

    # -- public API --------------------------------------------------------

    def is_needing_sync(self) -> bool:
        """True if remote or local changed since the last sync."""
        old = self.state.last_sync_epoch
        if self._remote_files(old):
            return True
        return self._newest_local_mtime() > old

    def sync(self, dry_run: bool = False) -> Dict[str, List[str]]:
        """Synchronise local and remote. Cloud wins on conflict.

        Returns the planned ``download``/``upload``/``deleted`` path lists.
        """
        from_epoch = self.state.last_sync_epoch
        new_epoch = int(time.time())

        rfiles = self._remote_files(0)
        remote_by_path = {f["pathfile"]: f for f in rfiles}
        remote_paths = sorted(remote_by_path)

        # Detect remote deletions versus last recorded state.
        old_remote = set(self.state.remote_pathfiles)
        deleted = sorted(p for p in old_remote if p not in remote_by_path)

        local_by_path = self._local_files()

        download: List[str] = []
        upload: List[str] = []

        # Local-only -> upload (unless the remote deleted it).
        for path in local_by_path:
            if path in deleted:
                continue
            if path not in remote_by_path:
                upload.append(path)

        # Remote-only -> download.
        for path in remote_by_path:
            if path not in local_by_path:
                download.append(path)

        # Present both sides -> resolve by checksum / modified time.
        for path in set(remote_by_path) & set(local_by_path):
            r = remote_by_path[path]
            l = local_by_path[path]
            if r.get("md5Checksum") and r["md5Checksum"] == l["md5Checksum"]:
                continue
            if path in download or path in upload:
                continue
            if r["_mtime_epoch"] >= l["modifiedTime"]:
                download.append(path)
            elif not from_epoch and l["md5Checksum"] and r.get("md5Checksum"):
                # Initial sync: only download; never re-upload existing files.
                continue
            elif r["_mtime_epoch"] >= from_epoch:
                download.append(path)
            else:
                if not from_epoch:
                    raise RuntimeError("Should never upload on init")
                upload.append(path)

        download.sort()
        upload.sort()

        print("Download:", ", ".join(download))
        print("Upload:", ", ".join(upload))
        print("Deleted:", ", ".join(deleted))

        if dry_run:
            return {"download": download, "upload": upload, "deleted": deleted}

        for path in download:
            self.file(path).download()
        for path in upload:
            self.file(path).upload()
        for path in deleted:
            self._archive_deleted(path)

        # Persist new state.
        self.state.remote_pathfiles = remote_paths
        self.state.last_sync_epoch = new_epoch
        self.state.save()

        return {"download": download, "upload": upload, "deleted": deleted}

    def _archive_deleted(self, pathfile: str) -> None:
        src = self.local_root / pathfile.lstrip("/")
        if not src.exists():
            return
        dest = config.CONFLICT_REMOVED_ROOT / pathfile.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"delete {pathfile}")
        shutil.move(str(src), str(dest))

    def clean_remote_duplicates(self) -> None:
        """Remove duplicate and empty remote files.

        Duplicates share (parent, name, md5); the oldest copy is kept.
        """
        files = [
            f for f in self.backend.list_all_files()
            if not f.get("mimeType", "").startswith(GOOGLE_APPS_PREFIX)
        ]

        groups: Dict[str, List[Dict]] = {}
        for f in files:
            parent = (f.get("parents") or ["__UNDEF__"])[0]
            key = f"{parent}/{f.get('name')}/{f.get('md5Checksum', '__UNDEF__')}"
            groups.setdefault(key, []).append(f)

        for key, dups in groups.items():
            if len(dups) < 2:
                continue
            dups.sort(key=lambda d: d.get("modifiedTime", ""))
            _keep, *rest = dups
            for dup in rest:
                self.backend.delete(dup["id"])
            print(f"#        Deleted count {len(rest)}")

        # Remove empty files.
        for f in files:
            if "size" not in f:
                raise RuntimeError(f"File missing size: {f}")
            if int(f["size"]) == 0:
                self.backend.delete(f["id"])
