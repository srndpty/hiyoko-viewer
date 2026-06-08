"""同梱リソースへのパス解決。

実行形態ごとに基準が異なる:

* PyInstaller 実行: 展開先 ``sys._MEIPASS`` を基準にする。
* それ以外（``python main.py`` / ``python -m hiyoko_viewer`` / ``pip install`` 後の
  ``hiyoko-viewer`` コマンド）: パッケージ同梱の ``hiyoko_viewer.assets`` を基準にする。
"""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path


def resource_path(relative_path: str) -> str:
    """``relative_path`` で指定したリソースの絶対パスを返す。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return str(Path(meipass) / relative_path)

    # パッケージに同梱したアセットを参照する（editable/通常 install 後でも解決可能）
    return str(files("hiyoko_viewer.assets").joinpath(relative_path))
