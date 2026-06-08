"""開発実行および PyInstaller 用のエントリスクリプト。

実体は ``src/hiyoko_viewer/app.py`` にある。ここでは ``src`` を import パスに
通したうえで ``main()`` を呼び出すだけの薄いラッパとする。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from hiyoko_viewer.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
