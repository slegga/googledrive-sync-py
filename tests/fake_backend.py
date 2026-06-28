"""In-memory DriveBackend implementation for tests.

Implements the same semantics as GoogleDriveBackend without touching the
network, so the sync logic can be exercised offline.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from googledrive_sync.backend import DriveBackend, FOLDER_MIME, GOOGLE_APPS_PREFIX


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FakeDriveBackend(DriveBackend):
    def __init__(self):
        self.files: Dict[str, Dict] = {}
        self.content: Dict[str, bytes] = {}
        self._counter = 0
        self.root_id = "root"

    # -- seeding helpers ---------------------------------------------------

    def _new_id(self) -> str:
        self._counter += 1
        return f"id{self._counter}"

    def add_folder(self, name: str, parent: str = "root", modified: str = None) -> str:
        fid = self._new_id()
        self.files[fid] = {
            "id": fid,
            "kind": "drive#file",
            "name": name,
            "mimeType": FOLDER_MIME,
            "parents": [parent],
            "modifiedTime": modified or _now_rfc3339(),
            "trashed": False,
        }
        return fid

    def add_file(
        self,
        name: str,
        parent: str,
        content: bytes,
        modified: Optional[str] = None,
    ) -> str:
        fid = self._new_id()
        self.files[fid] = {
            "id": fid,
            "kind": "drive#file",
            "name": name,
            "mimeType": "text/plain",
            "parents": [parent],
            "modifiedTime": modified or _now_rfc3339(),
            "trashed": False,
            "md5Checksum": hashlib.md5(content).hexdigest(),
            "size": str(len(content)),
        }
        self.content[fid] = content
        return fid

    # -- interface ---------------------------------------------------------

    def get_root(self) -> Dict:
        return {"id": self.root_id, "name": "My Drive"}

    def _alive(self) -> List[Dict]:
        return [f for f in self.files.values() if not f.get("trashed")]

    def list_folders(self) -> List[Dict]:
        return [f for f in self._alive() if f["mimeType"] == FOLDER_MIME]

    def list_changed_files(self, since_epoch: Optional[int] = None) -> List[Dict]:
        out = []
        for f in self._alive():
            if f["mimeType"] == FOLDER_MIME:
                continue
            if f["mimeType"].startswith(GOOGLE_APPS_PREFIX):
                continue
            out.append(f)
        return out

    def list_all_files(self) -> List[Dict]:
        return self.list_changed_files(None)

    def list_children(
        self, folder_id: str, dir_only: bool = False, name: Optional[str] = None
    ) -> List[Dict]:
        out = []
        for f in self._alive():
            if (f.get("parents") or [None])[0] != folder_id:
                continue
            if dir_only and f["mimeType"] != FOLDER_MIME:
                continue
            if name is not None and f["name"] != name:
                continue
            out.append(f)
        return out

    def find_files(self, name: str, parent_id: str) -> List[Dict]:
        return [
            f for f in self._alive()
            if f["name"] == name and (f.get("parents") or [None])[0] == parent_id
        ]

    def get_file(self, file_id: str) -> Dict:
        return self.files[file_id]

    def download(self, file_id: str) -> Optional[bytes]:
        return self.content.get(file_id)

    def create_folder(self, name: str, parent_id: str) -> Dict:
        fid = self.add_folder(name, parent_id)
        return self.files[fid]

    def upload_new(
        self, name: str, parent_id: str, local_path: str, mimetype: str
    ) -> Dict:
        data = Path(local_path).read_bytes()
        fid = self.add_file(name, parent_id, data)
        self.files[fid]["mimeType"] = mimetype
        return self.files[fid]

    def upload_update(self, file_id: str, local_path: str, mimetype: str) -> Dict:
        data = Path(local_path).read_bytes()
        self.content[file_id] = data
        self.files[file_id]["md5Checksum"] = hashlib.md5(data).hexdigest()
        self.files[file_id]["size"] = str(len(data))
        self.files[file_id]["modifiedTime"] = _now_rfc3339()
        return self.files[file_id]

    def delete(self, file_id: str) -> None:
        self.files.pop(file_id, None)
        self.content.pop(file_id, None)
