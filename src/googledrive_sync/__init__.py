"""googledrive-sync-py: a Dropbox-like Google Drive mirror.

Python rewrite of the Perl ``mojo-googledrive`` project.
"""

from .mirror import Mirror
from .drive_file import DriveFile
from .backend import DriveBackend, GoogleDriveBackend

__all__ = ["Mirror", "DriveFile", "DriveBackend", "GoogleDriveBackend"]
__version__ = "1.0.0"
