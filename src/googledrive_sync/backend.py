"""Semantic Google Drive backend.

Replaces the Perl ``http_request`` + hand-built ``q`` strings with a small,
intention-revealing interface. ``GoogleDriveBackend`` wraps
``google-api-python-client``; tests use ``FakeDriveBackend`` (see
``tests/fake_backend.py``) which implements the same semantics in memory.

``Mirror`` and ``DriveFile`` must only depend on this interface.
"""

from __future__ import annotations

import abc
import io
from typing import Dict, List, Optional

# Minimum metadata requested for each file (matches Perl INTERESTING_FIELDS).
INTERESTING_FIELDS = (
    "id,kind,name,mimeType,parents,modifiedTime,trashed,"
    "explicitlyTrashed,md5Checksum,size"
)

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_APPS_PREFIX = "application/vnd.google-apps"


def q_and(*terms: str) -> str:
    """Join non-empty query terms with ``and``."""
    return " and ".join(t for t in terms if t)


def epoch_to_rfc3339(epoch: int) -> str:
    """Convert a unix epoch to an RFC3339 UTC timestamp for Drive queries."""
    import datetime

    return (
        datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S")
    )


class DriveBackend(abc.ABC):
    """Semantic operations needed to mirror a Google Drive."""

    @abc.abstractmethod
    def get_root(self) -> Dict:
        """Return metadata for the Drive root folder ({id, name})."""

    @abc.abstractmethod
    def list_folders(self) -> List[Dict]:
        """Return all non-trashed folders ({id, name, parents, kind})."""

    @abc.abstractmethod
    def list_changed_files(self, since_epoch: Optional[int] = None) -> List[Dict]:
        """Return non-trashed binary files, optionally modified after epoch.

        Google-apps native files (Docs/Sheets/...) and folders are excluded.
        """

    @abc.abstractmethod
    def list_all_files(self) -> List[Dict]:
        """Return all non-trashed binary files (no time filter)."""

    @abc.abstractmethod
    def list_children(
        self, folder_id: str, dir_only: bool = False, name: Optional[str] = None
    ) -> List[Dict]:
        """Return non-trashed children of ``folder_id``."""

    @abc.abstractmethod
    def find_files(self, name: str, parent_id: str) -> List[Dict]:
        """Find non-trashed files named ``name`` directly under ``parent_id``."""

    @abc.abstractmethod
    def get_file(self, file_id: str) -> Dict:
        """Return metadata for a single file id."""

    @abc.abstractmethod
    def download(self, file_id: str) -> Optional[bytes]:
        """Return file content bytes, or None if not downloadable."""

    @abc.abstractmethod
    def create_folder(self, name: str, parent_id: str) -> Dict:
        """Create a folder and return its metadata."""

    @abc.abstractmethod
    def upload_new(
        self, name: str, parent_id: str, local_path: str, mimetype: str
    ) -> Dict:
        """Upload a new file and return its metadata."""

    @abc.abstractmethod
    def upload_update(self, file_id: str, local_path: str, mimetype: str) -> Dict:
        """Replace the content of an existing file and return its metadata."""

    @abc.abstractmethod
    def delete(self, file_id: str) -> None:
        """Permanently delete a file by id."""


class GoogleDriveBackend(DriveBackend):
    """Real backend backed by ``google-api-python-client``."""

    def __init__(self, credentials):
        from googleapiclient.discovery import build

        # cache_discovery=False avoids noisy warnings on modern oauth2 creds.
        self.service = build(
            "drive", "v3", credentials=credentials, cache_discovery=False
        )

    # -- internal helpers --------------------------------------------------

    def _list(self, q: str, dir_fields: str = INTERESTING_FIELDS) -> List[Dict]:
        files: List[Dict] = []
        page_token = None
        fields = f"nextPageToken,files({dir_fields})"
        while True:
            resp = (
                self.service.files()
                .list(
                    q=q,
                    fields=fields,
                    pageSize=1000,
                    pageToken=page_token,
                    spaces="drive",
                )
                .execute()
            )
            files.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return files

    # -- interface ---------------------------------------------------------

    def get_root(self) -> Dict:
        return self.service.files().get(fileId="root", fields="id,name").execute()

    def list_folders(self) -> List[Dict]:
        q = q_and("trashed = false", f"mimeType = '{FOLDER_MIME}'")
        return self._list(q, dir_fields="id,name,parents,kind")

    def list_changed_files(self, since_epoch: Optional[int] = None) -> List[Dict]:
        terms = ["trashed = false"]
        if since_epoch:
            terms.append(f"modifiedTime > '{epoch_to_rfc3339(since_epoch)}'")
        terms.append(f"mimeType != '{FOLDER_MIME}'")
        for sub in ("map", "document", "presentation", "spreadsheet"):
            terms.append(f"mimeType != '{GOOGLE_APPS_PREFIX}.{sub}'")
        files = self._list(q_and(*terms))
        return [
            f for f in files
            if not f.get("mimeType", "").startswith(GOOGLE_APPS_PREFIX)
        ]

    def list_all_files(self) -> List[Dict]:
        return self.list_changed_files(since_epoch=None)

    def list_children(
        self, folder_id: str, dir_only: bool = False, name: Optional[str] = None
    ) -> List[Dict]:
        terms = [f"'{folder_id}' in parents", "trashed = false"]
        if dir_only:
            terms.append(f"mimeType = '{FOLDER_MIME}'")
        if name is not None:
            terms.append(f"name = '{_escape(name)}'")
        return self._list(q_and(*terms))

    def find_files(self, name: str, parent_id: str) -> List[Dict]:
        q = q_and(
            f"name = '{_escape(name)}'",
            "trashed = false",
            f"'{parent_id}' in parents",
        )
        return self._list(q)

    def get_file(self, file_id: str) -> Dict:
        return (
            self.service.files()
            .get(fileId=file_id, fields=INTERESTING_FIELDS)
            .execute()
        )

    def download(self, file_id: str) -> Optional[bytes]:
        from googleapiclient.http import MediaIoBaseDownload
        from googleapiclient.errors import HttpError

        request = self.service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        try:
            done = False
            while not done:
                _status, done = downloader.next_chunk()
        except HttpError as exc:
            # Google-apps files cannot be downloaded directly; skip like Perl.
            if exc.resp.status == 403:
                return None
            raise
        return buffer.getvalue()

    def create_folder(self, name: str, parent_id: str) -> Dict:
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        return (
            self.service.files()
            .create(body=body, fields=INTERESTING_FIELDS)
            .execute()
        )

    def upload_new(
        self, name: str, parent_id: str, local_path: str, mimetype: str
    ) -> Dict:
        from googleapiclient.http import MediaFileUpload

        body = {"name": name, "parents": [parent_id]}
        media = MediaFileUpload(local_path, mimetype=mimetype, resumable=True)
        return (
            self.service.files()
            .create(body=body, media_body=media, fields=INTERESTING_FIELDS)
            .execute()
        )

    def upload_update(self, file_id: str, local_path: str, mimetype: str) -> Dict:
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(local_path, mimetype=mimetype, resumable=True)
        return (
            self.service.files()
            .update(fileId=file_id, media_body=media, fields=INTERESTING_FIELDS)
            .execute()
        )

    def delete(self, file_id: str) -> None:
        self.service.files().delete(fileId=file_id).execute()


def _escape(value: str) -> str:
    """Escape single quotes/backslashes for a Drive query literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")
