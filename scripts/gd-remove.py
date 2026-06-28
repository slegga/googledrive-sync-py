#!/usr/bin/env python3
import sys
from googledrive_sync.cli import gd_remove
if __name__ == '__main__':
    sys.argv[0] = sys.argv[0].removesuffix('.exe')
    sys.exit(gd_remove())
