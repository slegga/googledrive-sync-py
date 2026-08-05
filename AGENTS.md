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
Egenlagde scripts (`gd-sync`, `gd-clean`, `gd-remove`) ligger i `scripts/`.
Prosjektet bruker ikke virtuelt miljø i det hele tatt — ingen `.venv/`, ingen
`pip install`, ingenting som må aktiveres. Legg aldri scripts i en katalog som
genereres av en pakkemanager; de blir overskrevet.

Scriptene kjøres med **uv** og er selvforsynte. De starter med

```
#!/usr/bin/env -S uv run --quiet --script
```

og deklarerer avhengighetene sine i en PEP 723-blokk. De finner `src/` selv
(relativt til fila), så de trenger verken `PYTHONPATH`, aktivert virtuelt miljø
eller `pip install` — hverken manuelt eller fra cron.

Bruk aldri absolutt sti til `uv` i shebangen (f.eks. `/opt/homebrew/bin/uv`);
`env -S uv` gjør at samme fil virker på macOS, Ubuntu og Raspberry Pi OS. `--quiet`
gjør at uv er stille når alt går bra, slik at cron bare sender mail ved ekte feil.

Tidligere lå det shell-skall i `bin/` som aktiverte `.venv` og satte `PYTHONPATH`.
De er fjernet — uv-shebangen gjør jobben deres. Ikke lag nye: kall `scripts/*.py`
direkte, både manuelt og fra cron.

## Compatibility with existing setup
Credentials live in `~/.google-drive.yml` and sync state in
`~/etc/googledrive.yml` — the same files used by the Perl version. Preserve the
formats so a machine can switch between the Perl and Python implementations.
