# AGENTS.md

Guidance for AI agents working on `googledrive-sync-py`.

This project is a Python rewrite of the Perl `mojo-googledrive`. The following
are **deliberate design choices**. Do not "fix" them without asking.

## Fail-hard error handling
The original used `die` as its primary error strategy. The sync must stop hard
on unexpected responses from Google Drive instead of continuing in an unknown
state and risking corruption of local or remote files.

In Python this means: raise exceptions (often `RuntimeError`) on unexpected
conditions. Do **not** wrap remote calls in broad `try/except` that swallows
errors, and do **not** add silent retries. Let it crash loudly.

## Unimplemented paths
The Perl code used `...` (yada-yada) to mark code paths that are not yet
handled, raising "Unimplemented" if reached. The Python equivalent is
`raise NotImplementedError(...)`. Keep these markers — a hard failure on an
unhandled path is the desired behaviour.

## Backend abstraction
Remote operations go through the semantic `DriveBackend` interface
(`backend.py`). `GoogleDriveBackend` wraps `google-api-python-client`;
`FakeDriveBackend` (in tests) implements the same semantics over an in-memory
store. `Mirror`/`DriveFile` must only talk to the backend interface, never to
`googleapiclient` directly, so the logic stays testable offline.

## Custom scripts in `scripts/`
Egenlagde scripts (`gd-sync`, `gd-clean`, `gd-remove`) ligger i `scripts/`, **ikke**
i `.venv/bin/`. `.venv/bin/` genereres av pip og skal ikke ha manuelt plasserte filer
— de blir overskrevet/regenerert. `project.scripts` i `pyproject.toml` definerer
entry points; `scripts/`-filene er frittstående alternativer med `#!/usr/bin/env python3`.

Det skal også lages shell-skall rundt disse (f.eks. `gd-sync.sh`) som kaller
python-skriptene i `scripts/` med rett `PYTHONPATH` og virtuelt miljø, slik at
de kan kjøres uten å ha `.venv/bin/` i PATH på forhånd.

## Compatibility with existing setup
Credentials live in `~/.google-drive.yml` and sync state in
`~/etc/googledrive.yml` — the same files used by the Perl version. Preserve the
formats so a machine can switch between the Perl and Python implementations.
