"""Configuration and persistent sync state.

Mirrors the Perl version's use of ``~/.google-drive.yml`` (OAuth credentials)
and ``~/etc/googledrive.yml`` (sync state) so the Python and Perl
implementations stay interchangeable on the same machine.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

# Default locations, matching the Perl implementation.
HOME = Path(os.path.expanduser("~"))
DEFAULT_LOCAL_ROOT = HOME / "googledrive"
DEFAULT_CREDENTIALS_FILE = HOME / ".google-drive.yml"
DEFAULT_STATE_DIR = HOME / "etc"
DEFAULT_STATE_FILE = DEFAULT_STATE_DIR / "googledrive.yml"

# Backup directories used during conflict resolution (kept identical to Perl).
BACKUP_ROOT = HOME / ".googledrive" / "conflict-remove"
CONFLICT_REMOVED_ROOT = HOME / ".googledrive" / "conflict-removed"

SCOPES = ["https://www.googleapis.com/auth/drive"]
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Filenames/glob patterns never synced in either direction. Patterns without a
# "/" are matched against the basename; patterns with a "/" against the full
# remote-relative pathfile. Matched case-insensitively.
DEFAULT_IGNORE = [
    ".DS_Store",
    "._*",
    ".Spotlight-V100",
    ".Trashes",
    "Thumbs.db",
    "*.swp",
    "*.tmp",
]


def is_ignored(pathfile: str, patterns=DEFAULT_IGNORE) -> bool:
    """Return True if ``pathfile`` matches any ignore pattern."""
    import fnmatch

    name = pathfile.rsplit("/", 1)[-1]
    for pattern in patterns:
        target = pathfile if "/" in pattern else name
        if fnmatch.fnmatch(target.lower(), pattern.lower()):
            return True
    return False


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file, returning an empty dict if missing or empty."""
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def dump_yaml(path: Path, data: Dict[str, Any]) -> None:
    """Write ``data`` to ``path`` as YAML, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, default_flow_style=False)


class State:
    """Persistent sync state stored in ``~/etc/googledrive.yml``.

    Tracks ``last_sync_epoch`` and the list of ``remote_pathfiles`` seen during
    the previous sync (used to detect remote deletions).
    """

    def __init__(self, state_file: Path = DEFAULT_STATE_FILE):
        self.state_file = Path(state_file)
        if self.state_file.is_symlink() and not self.state_file.exists():
            raise RuntimeError(f"{self.state_file} is a broken symlink.")
        self.data: Dict[str, Any] = load_yaml(self.state_file)
        self.data.setdefault("last_sync_epoch", 0)

    @property
    def last_sync_epoch(self) -> int:
        try:
            return int(self.data.get("last_sync_epoch", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @last_sync_epoch.setter
    def last_sync_epoch(self, value: int) -> None:
        self.data["last_sync_epoch"] = int(value)

    @property
    def remote_pathfiles(self) -> list:
        return list(self.data.get("remote_pathfiles", []) or [])

    @remote_pathfiles.setter
    def remote_pathfiles(self, value: list) -> None:
        self.data["remote_pathfiles"] = sorted(value)

    def save(self) -> None:
        dump_yaml(self.state_file, self.data)
