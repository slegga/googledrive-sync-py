#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "google-api-python-client>=2.0.0",
#     "google-auth>=2.0.0",
#     "google-auth-oauthlib>=1.0.0",
#     "PyYAML>=6.0",
# ]
# ///
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from googledrive_sync.cli import gd_clean

if __name__ == "__main__":
    sys.argv[0] = sys.argv[0].removesuffix(".exe")
    sys.exit(gd_clean())
