"""Command-line entry points.

Replaces the Perl scripts ``gd-sync.pl``, ``gd-clean.pl`` and ``gd-remove.pl``.
"""

from __future__ import annotations

import argparse
import functools
import os
import socket
import sys
from collections.abc import Callable
from pathlib import Path

from . import auth, config
from .backend import GoogleDriveBackend
from .mirror import Mirror


def _build_mirror(debug: bool = False) -> Mirror:
    credentials = auth.load_credentials()
    backend = GoogleDriveBackend(credentials)
    return Mirror(backend, debug=debug)


def _skip_when_offline(func: Callable[..., int]) -> Callable[..., int]:
    """Quietly skip a run when the machine simply cannot reach Google.

    A deliberate, narrow exception to the fail-hard policy (AGENTS.md): only a
    genuine "no network/DNS" condition is swallowed. Real API errors
    (``googleapiclient.errors.HttpError``) and bad credentials
    (``google.auth.exceptions.RefreshError``) are not caught and still crash.

    Prints to stdout and exits 0, so a manual run shows the note while cron
    (``1>/dev/null``) stays silent instead of mailing a traceback.
    """

    @functools.wraps(func)
    def wrapper(argv: list[str] | None = None) -> int:
        from httplib2 import ServerNotFoundError
        from google.auth.exceptions import TransportError

        try:
            return func(argv)
        except (ServerNotFoundError, socket.gaierror, TransportError):
            print("Google Drive is unreachable (no network/DNS) - skipping this run.")
            return 0

    return wrapper


@_skip_when_offline
def gd_sync(argv=None) -> int:
    """Sync the local directory with Google Drive (like Dropbox)."""
    parser = argparse.ArgumentParser(
        prog="gd-sync",
        description="Synchronise ~/googledrive with Google Drive.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="sync",
        choices=["sync", "dryrun", "force", "init", "auth"],
        help=(
            "sync (default), dryrun (preview), force (always sync), "
            "init (full first sync), auth (authorize via browser)"
        ),
    )
    parser.add_argument("--debug", action="store_true", help="Verbose output")
    args = parser.parse_args(argv)

    if args.command == "auth":
        auth.run_init_flow()
        print("Authorization complete. Credentials saved to "
              f"{config.DEFAULT_CREDENTIALS_FILE}")
        return 0

    mirror = _build_mirror(debug=args.debug)

    if args.command == "dryrun":
        mirror.sync(dry_run=True)
    elif args.command in ("force", "init"):
        mirror.sync()
    elif mirror.is_needing_sync():
        mirror.sync()
    else:
        print("No need for sync.")
    return 0


def gd_clean(argv=None) -> int:
    """Remove empty local folders and duplicate/empty remote files."""
    parser = argparse.ArgumentParser(
        prog="gd-clean",
        description="Clean empty local folders and remote duplicates.",
    )
    parser.add_argument("--debug", action="store_true", help="Verbose output")
    args = parser.parse_args(argv)

    _remove_empty_local_dirs(config.DEFAULT_LOCAL_ROOT)

    mirror = _build_mirror(debug=args.debug)
    mirror.clean_remote_duplicates()
    return 0


def gd_remove(argv=None) -> int:
    """Remove a file locally and on Google Drive."""
    parser = argparse.ArgumentParser(
        prog="gd-remove",
        description="Remove a file from the local mirror and Google Drive.",
    )
    parser.add_argument("pathfile", help="Remote-relative path, e.g. /dir/file.txt")
    parser.add_argument("--debug", action="store_true", help="Verbose output")
    args = parser.parse_args(argv)

    pathfile = args.pathfile
    # Accept absolute local paths under the mirror root for convenience.
    local_root = str(config.DEFAULT_LOCAL_ROOT)
    if pathfile.startswith(local_root):
        pathfile = pathfile[len(local_root):]
    if not pathfile.startswith("/"):
        pathfile = "/" + pathfile

    mirror = _build_mirror(debug=args.debug)
    result = mirror.file(pathfile).remove()
    print(result.last_message)
    return 0


def _remove_empty_local_dirs(root: Path) -> None:
    """Delete empty directories under ``root`` (deepest first)."""
    root = Path(root)
    if not root.exists():
        return
    for dirpath, _dirs, _files in sorted(
        os.walk(root, topdown=False), key=lambda x: len(x[0]), reverse=True
    ):
        path = Path(dirpath)
        if path == root:
            continue
        try:
            if not any(path.iterdir()):
                print(f"delete {path}")
                path.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(gd_sync())
