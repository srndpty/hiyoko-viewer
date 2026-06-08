import os
import sys

from hiyoko_viewer.config import constants
from hiyoko_viewer.core import resources


def test_supported_extensions_are_normalized_and_unique() -> None:
    assert constants.SUPPORTED_EXTENSIONS == sorted(set(constants.SUPPORTED_EXTENSIONS))
    assert all(ext.startswith(".") for ext in constants.SUPPORTED_EXTENSIONS)
    assert all(ext == ext.lower() for ext in constants.SUPPORTED_EXTENSIONS)


def test_zoom_factors_are_inverse() -> None:
    assert constants.ZOOM_IN_FACTOR > 1
    assert constants.ZOOM_OUT_FACTOR == 1 / constants.ZOOM_IN_FACTOR


def test_resource_path_uses_pyinstaller_meipass(monkeypatch) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\bundle", raising=False)

    assert resources.resource_path("app_icon.ico") == os.path.join(r"C:\bundle", "app_icon.ico")


def test_resource_path_points_to_packaged_asset_without_meipass(monkeypatch) -> None:
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    path = resources.resource_path("app_icon.ico")

    # PyInstaller 以外の実行ではパッケージ同梱アセットを指し、実体が存在する
    assert path.endswith(os.path.join("hiyoko_viewer", "assets", "app_icon.ico"))
    assert os.path.exists(path)
