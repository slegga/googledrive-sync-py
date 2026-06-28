"""A single file/path mirrored between local disk and Google Drive.

Python rewrite of ``Mojo::GoogleDrive::Mirror::File``. Talks only to a
``DriveBackend``; all remote-query plumbing lives in the backend.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

from . import config
from .backend import DriveBackend, FOLDER_MIME


def _md5_hex(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class DriveFile:
    """One path inside the mirror.

    ``pathfile`` is the remote-relative POSIX path, e.g. ``/dir/file.txt``.
    """

    def __init__(
        self,
        backend: DriveBackend,
        pathfile: str,
        *,
        local_root: Path = config.DEFAULT_LOCAL_ROOT,
        backup_root: Path = config.BACKUP_ROOT,
        metadata: Optional[Dict] = None,
        debug: bool = False,
    ):
        if not pathfile:
            raise ValueError("pathfile is required")
        self.backend = backend
        self.pathfile = pathfile
        self.local_root = Path(local_root)
        self.backup_root = Path(backup_root)
        self.metadata: Dict = dict(metadata) if metadata else {}
        self.debug = debug
        self.last_message = ""
        self._resolved_metadata: Optional[Dict] = None

    # -- path helpers ------------------------------------------------------

    @property
    def parts(self) -> List[str]:
        return [p for p in PurePosixPath(self.pathfile).parts if p not in ("/", "")]

    @property
    def name(self) -> str:
        return PurePosixPath(self.pathfile).name

    @property
    def lfile(self) -> Path:
        """Absolute path of the local mirror copy."""
        return self.local_root / self.pathfile.lstrip("/")

    @property
    def backup_file(self) -> Path:
        return self.backup_root / self.pathfile.lstrip("/")

    # -- mime --------------------------------------------------------------

    def file_mime_type(self) -> str:
        guessed, _ = mimetypes.guess_type(str(self.lfile))
        return guessed or "application/octet-stream"

    # -- remote resolution -------------------------------------------------

    def resolve_parent_id(self, create: bool = False) -> Optional[str]:
        """Return the Drive id of the folder containing this path.

        Walks folders from root. When ``create`` is True, missing folders are
        created. When False, returns None if any ancestor is missing.
        """
        parent_id = self.backend.get_root()["id"]
        for part in self.parts[:-1]:
            children = self.backend.list_children(
                parent_id, dir_only=True, name=part
            )
            match = next((c for c in children if c.get("name") == part), None)
            if match is None:
                if not create:
                    return None
                match = self.backend.create_folder(part, parent_id)
            parent_id = match["id"]
        return parent_id

    def get_metadata(self) -> Optional[Dict]:
        """Return remote metadata (with id) for this path, or None if absent."""
        if self.metadata.get("id"):
            return self.metadata
        if self._resolved_metadata is not None:
            return self._resolved_metadata or None

        if self.pathfile == "/":
            self._resolved_metadata = self.backend.get_root()
            return self._resolved_metadata

        parent_id = self.resolve_parent_id(create=False)
        if parent_id is None:
            self._resolved_metadata = {}
            return None
        matches = self.backend.find_files(self.name, parent_id)
        if len(matches) > 1:
            raise RuntimeError(
                f"Multiple remote files named {self.name!r} under one parent "
                f"for {self.pathfile!r}; refusing to guess."
            )
        self._resolved_metadata = matches[0] if matches else {}
        return self._resolved_metadata or None

    def path_resolve(self) -> List[Optional[Dict]]:
        """Return metadata for each path component (root first, file last)."""
        result: List[Optional[Dict]] = [self.backend.get_root()]
        parent_id = result[0]["id"]
        last = len(self.parts) - 1
        for i, part in enumerate(self.parts):
            dir_only = i < last
            children = self.backend.list_children(
                parent_id, dir_only=dir_only, name=part
            )
            match = next((c for c in children if c.get("name") == part), None)
            result.append(match)
            if match is None:
                # Remaining components cannot exist if an ancestor is missing.
                result.extend([None] * (last - i))
                break
            parent_id = match["id"]
        return result

    # -- operations --------------------------------------------------------

    def list(self) -> List["DriveFile"]:
        """List child files when this path is a folder."""
        if self.pathfile == "/":
            folder_id = self.backend.get_root()["id"]
        else:
            meta = self.get_metadata()
            if not meta:
                return []
            if meta.get("mimeType") != FOLDER_MIME:
                raise RuntimeError(f"{self.pathfile!r} is not a folder.")
            folder_id = meta["id"]
        children = self.backend.list_children(folder_id)
        out = []
        base = self.pathfile.rstrip("/")
        for child in children:
            child_path = f"{base}/{child['name']}"
            out.append(
                DriveFile(
                    self.backend,
                    child_path,
                    local_root=self.local_root,
                    backup_root=self.backup_root,
                    metadata=child,
                    debug=self.debug,
                )
            )
        return out

    def make_path(self) -> "DriveFile":
        """Ensure the remote directory chain for this path exists."""
        self.resolve_parent_id(create=True)
        self._resolved_metadata = None
        return self

    def download(self) -> Optional["DriveFile"]:
        meta = self.get_metadata()
        if not meta or not meta.get("id"):
            if self.lfile.is_file():
                # Already present locally; nothing to do (matches Perl).
                return None
            raise RuntimeError(
                f"Cannot download {self.pathfile!r}: not found on remote."
            )
        content = self.backend.download(meta["id"])
        if content is None:
            return None
        self.lfile.parent.mkdir(parents=True, exist_ok=True)
        if self.lfile.is_file():
            # Back up the existing copy before overwriting.
            self.backup_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.lfile, self.backup_file)
        with open(self.lfile, "wb") as fh:
            fh.write(content)
        return self

    def upload(self) -> "DriveFile":
        if not self.lfile.is_file():
            raise RuntimeError(f"Local file missing: {self.lfile}")
        mimetype = self.file_mime_type()
        meta = self.get_metadata()
        if meta and meta.get("id"):
            new_meta = self.backend.upload_update(
                meta["id"], str(self.lfile), mimetype
            )
        else:
            parent_id = self.resolve_parent_id(create=True)
            if not parent_id:
                raise RuntimeError(
                    f"Could not resolve remote parent for {self.pathfile!r}"
                )
            new_meta = self.backend.upload_new(
                self.name, parent_id, str(self.lfile), mimetype
            )
        self.metadata = new_meta
        self._resolved_metadata = new_meta
        return self

    def remove(self) -> "DriveFile":
        """Delete the file locally and remotely; record a status message."""
        messages = []
        local = self.lfile
        if local.is_file():
            local.unlink()
            messages.append(f"Removed local file: {local}")
        else:
            messages.append(f"Local file does not exist: {local}")
        meta = self.get_metadata()
        if meta and meta.get("id"):
            self.backend.delete(meta["id"])
            messages.append(f"Removed remote file: {self.pathfile}")
        else:
            messages.append(f"Remote file not found: {self.pathfile}")
        self.last_message = "\n".join(messages)
        return self

    def need_sync(self) -> bool:
        meta = self.get_metadata()
        if meta and meta.get("id") and self.lfile.is_file():
            return meta.get("md5Checksum") != _md5_hex(self.lfile)
        return True
