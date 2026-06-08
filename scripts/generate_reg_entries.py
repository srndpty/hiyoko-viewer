"""register_app.reg の FileAssociations / AssocFile 定義を生成する補助スクリプト。"""

from __future__ import annotations

import os
import sys

# src 配下の hiyoko_viewer パッケージを import できるようにする
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from hiyoko_viewer.config.constants import SUPPORTED_EXTENSIONS  # noqa: E402

# --- セクション2: FileAssociations の生成 ---
print("=" * 20)
print("以下の内容を [Capabilities\\FileAssociations] セクションに貼り付けてください:")
print("=" * 20)
for ext in sorted(SUPPORTED_EXTENSIONS):
    ext_upper = ext.replace(".", "").upper()
    print(f'"{ext}"="HiyokoViewer.AssocFile.{ext_upper}"')

print("\n\n")

# --- セクション3: AssocFile 定義の生成 ---
print("=" * 20)
print("以下の内容をセクション3 (AssocFile 定義) として貼り付けてください:")
print("=" * 20)
for ext in sorted(SUPPORTED_EXTENSIONS):
    ext_upper = ext.replace(".", "").upper()
    print(f"[HKEY_CURRENT_USER\\Software\\Classes\\HiyokoViewer.AssocFile.{ext_upper}]")
    print(f'@="{ext_upper} Image File"')
    print("")  # 空行
