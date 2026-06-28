"""OAuth credential handling.

Replaces the Perl ``OAuth::Cmdline::GoogleDrive`` with ``google-auth``.
Credentials are read from and written back to ``~/.google-drive.yml`` so the
file stays compatible with the Perl tooling (keys: ``client_id``,
``client_secret``, ``access_token``, ``refresh_token``, ``token_uri``,
``expires``).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from . import config


def _to_credentials(data: dict) -> Credentials:
    if not data.get("refresh_token"):
        raise RuntimeError(
            "No refresh_token in credentials file. Run `gd-sync init` to "
            "authorize, or copy ~/.google-drive.yml from another machine."
        )
    return Credentials(
        token=data.get("access_token"),
        refresh_token=data["refresh_token"],
        token_uri=data.get("token_uri") or config.DEFAULT_TOKEN_URI,
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=config.SCOPES,
    )


def _persist(creds: Credentials, data: dict, path: Path) -> None:
    """Write refreshed token fields back into the YAML credential file."""
    data["access_token"] = creds.token
    if creds.refresh_token:
        data["refresh_token"] = creds.refresh_token
    if creds.expiry is not None:
        data["expires"] = int(creds.expiry.timestamp())
    config.dump_yaml(path, data)


def load_credentials(
    credentials_file: Path = config.DEFAULT_CREDENTIALS_FILE,
) -> Credentials:
    """Load credentials, refreshing the access token when needed.

    Refreshed tokens are written back to ``credentials_file``.
    """
    path = Path(credentials_file)
    data = config.load_yaml(path)
    if not data:
        raise RuntimeError(
            f"Credentials file {path} is missing or empty. "
            "Run `gd-sync init` to authorize."
        )
    creds = _to_credentials(data)
    if not creds.valid:
        creds.refresh(Request())
        _persist(creds, data, path)
    return creds


def run_init_flow(
    credentials_file: Path = config.DEFAULT_CREDENTIALS_FILE,
    port: int = 8082,
) -> Credentials:
    """Interactive OAuth flow to (re)generate a refresh token.

    Reuses ``client_id``/``client_secret`` from ``~/.google-drive.yml`` and
    opens a browser to complete consent, mirroring ``google-drive-init.pl``.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    path = Path(credentials_file)
    data = config.load_yaml(path)
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    if not client_id or not client_secret:
        raise RuntimeError(
            f"client_id/client_secret missing from {path}. Add them first "
            "(obtain from Google Cloud Console)."
        )
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": data.get("token_uri") or config.DEFAULT_TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, config.SCOPES)
    creds = flow.run_local_server(port=port)

    data["client_id"] = client_id
    data["client_secret"] = client_secret
    data["token_uri"] = data.get("token_uri") or config.DEFAULT_TOKEN_URI
    _persist(creds, data, path)
    return creds
