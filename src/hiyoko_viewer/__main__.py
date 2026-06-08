"""``python -m hiyoko_viewer`` で起動するためのエントリポイント。"""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
