from __future__ import annotations

import os
import sys


def resource_path(relative_path: str) -> str:
    """開発時とPyInstaller実行時の両方で、リソースへの正しいパスを取得する"""
    try:
        base_path: str = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
