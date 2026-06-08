"""実行形態をまたいで壊れやすい「import 解決」と「リソース解決」の統合スモーク。

単体メソッドテストでは捕まらない、パッケージ分割・src レイアウト・エントリポイント
追加に伴う破綻（import 失敗、アセット同梱漏れ）を早期に検出する。
"""

import importlib
import os
import runpy


def test_public_modules_import_cleanly() -> None:
    # python -m hiyoko_viewer / hiyoko-viewer / PyInstaller のいずれもこの import を辿る
    for name in (
        "hiyoko_viewer",
        "hiyoko_viewer.app",
        "hiyoko_viewer.ui.main_window",
        "hiyoko_viewer.ui.mixins.rendering",
        "hiyoko_viewer.ui.mixins.navigation",
        "hiyoko_viewer.ui.mixins.input",
        "hiyoko_viewer.ui.dialogs.metadata_dialog",
        "hiyoko_viewer.services.image_loader",
        "hiyoko_viewer.core.metadata",
        "hiyoko_viewer.core.sorting",
        "hiyoko_viewer.core.resources",
    ):
        assert importlib.import_module(name) is not None


def test_app_icon_is_packaged_and_resolvable() -> None:
    # console-script / editable install でもアイコンを見つけられること（PyInstaller 非依存の経路）
    from hiyoko_viewer.core.resources import resource_path

    icon_path = resource_path("app_icon.ico")

    assert os.path.exists(icon_path)


def test_image_viewer_composes_all_mixins() -> None:
    from PyQt6.QtWidgets import QMainWindow

    from hiyoko_viewer.ui.main_window import ImageViewer
    from hiyoko_viewer.ui.mixins.input import InputEventMixin
    from hiyoko_viewer.ui.mixins.navigation import NavigationMixin
    from hiyoko_viewer.ui.mixins.rendering import RenderingMixin

    mro = ImageViewer.__mro__
    assert RenderingMixin in mro
    assert NavigationMixin in mro
    assert InputEventMixin in mro
    # 入力イベント系の super() チェーンが QMainWindow に到達するための前提
    assert mro.index(InputEventMixin) < mro.index(QMainWindow)


def test_helper_script_runs_standalone() -> None:
    # scripts/ 配下のヘルパが pythonpath 経由でパッケージを解決できること
    runpy.run_module("generate_reg_entries", run_name="__main__")
