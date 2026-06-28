# googledrive-sync-py

A Dropbox-like **two-way mirror** between a local directory (`~/googledrive`)
and Google Drive. This is a Python rewrite of the Perl
[`mojo-googledrive`](../mojo-googledrive) project.

On conflicting changes the **cloud copy wins** (the local copy is backed up
first).

## Installation

```bash
cd googledrive-sync-py
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs three console commands: `gd-sync`, `gd-clean`, `gd-remove`.

## Setup

1. Create the local mirror directory:

   ```bash
   mkdir -p ~/googledrive ~/etc
   ```

2. Provide credentials in `~/.google-drive.yml` (same file the Perl version
   uses). Copy it from an existing machine, or create one with at least your
   OAuth `client_id` and `client_secret` (from the Google Cloud Console):

   ```yaml
   client_id: XXXXXXXX.apps.googleusercontent.com
   client_secret: YYYYYYYYYYYYYYYYYYYYYY
   ```

3. Authorize (opens a browser to `localhost:8082` to log in to Google):

   ```bash
   gd-sync auth
   ```

   This stores `access_token` and `refresh_token` back into
   `~/.google-drive.yml`. Re-run it if the refresh token ever stops working
   (the Perl equivalent was `script/google-drive-init.pl`).

## Usage

```bash
gd-sync            # normal sync (only runs if something changed)
gd-sync dryrun     # preview the download/upload/delete plan, change nothing
gd-sync force      # sync even if nothing seems to have changed
gd-sync init       # full first sync (download everything)
gd-sync --debug    # verbose output

gd-clean           # remove empty local folders + duplicate/empty remote files
gd-remove /path/file.txt   # delete a file locally and on Google Drive
```

Sync state (last sync time and the previous remote file list) is kept in
`~/etc/googledrive.yml`, compatible with the Perl version.

### Ignored files

Junk/temp files are never synced in either direction. The default ignore list
(`config.DEFAULT_IGNORE`) covers `.DS_Store`, `._*` AppleDouble files,
`.Spotlight-V100`, `.Trashes`, `Thumbs.db`, `*.swp` and `*.tmp`. Patterns
without a `/` match the filename; patterns with a `/` match the full
remote-relative path. Pass a custom list to `Mirror(..., ignore=[...])` to
override.

## How it works

| Concern | Implementation |
| --- | --- |
| Drive API | `google-api-python-client` behind a semantic `DriveBackend` |
| OAuth | `google-auth` / `google-auth-oauthlib` (`auth.py`) |
| Config / state | `PyYAML` (`config.py`) reusing the Perl YAML files |
| MIME detection | stdlib `mimetypes` |
| Mirror engine | `mirror.Mirror`; per-file ops in `drive_file.DriveFile` |

Sync algorithm (faithful to the original):

1. List remote (non-Google-Docs) files and resolve their full paths.
2. Compare with the previous run to detect remote deletions.
3. Scan local files and diff against remote:
   - local-only -> upload
   - remote-only -> download
   - both, differing MD5 -> cloud wins by modified time (download); only on a
     non-initial run will a newer local file be uploaded.
4. Apply downloads, uploads, and archive remotely-deleted files under
   `~/.googledrive/conflict-removed/`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests run fully offline using an in-memory `FakeDriveBackend`
(`tests/fake_backend.py`) that implements the same `DriveBackend` semantics as
the real Google backend.

See [AGENTS.md](AGENTS.md) for deliberate design conventions (notably
fail-hard error handling) — please read it before changing behaviour.

## License

CC0 1.0 Universal (see `LICENSE`), same as the original project.
