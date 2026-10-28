"""ファイルをエクスプローラー（Finder）で開き、そのファイルを選択状態にする。"""

from __future__ import annotations

import os
import subprocess
import sys


def reveal_in_file_manager(file_path: str) -> None:
    """``file_path`` を含むフォルダを開き、ファイルを選択した状態にする。

    ファイルが存在しない場合は :class:`FileNotFoundError` を送出する。
    """
    path = os.path.normpath(os.path.abspath(file_path))
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    if sys.platform == "win32":
        # 引数リストで渡すと "/select,<path>" 全体がクォートされ、explorer が解釈できない。
        # コマンドライン文字列をそのまま CreateProcess へ渡し、パス部分だけをクォートする。
        # explorer は成功しても終了コード 1 を返すことがあるので、終了コードは見ない。
        subprocess.Popen(f'explorer.exe /select,"{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        # Linux は選択状態にする共通手段がないため、フォルダを開くだけにする
        subprocess.Popen(["xdg-open", os.path.dirname(path)])
