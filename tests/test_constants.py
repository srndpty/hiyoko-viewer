import sys

import constants


def test_supported_extensions_are_normalized_and_unique() -> None:
    assert constants.SUPPORTED_EXTENSIONS == sorted(set(constants.SUPPORTED_EXTENSIONS))
    assert all(ext.startswith(".") for ext in constants.SUPPORTED_EXTENSIONS)
    assert all(ext == ext.lower() for ext in constants.SUPPORTED_EXTENSIONS)


def test_zoom_factors_are_inverse() -> None:
    assert constants.ZOOM_IN_FACTOR > 1
    assert constants.ZOOM_OUT_FACTOR == 1 / constants.ZOOM_IN_FACTOR


def test_resource_path_uses_pyinstaller_meipass(monkeypatch) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\bundle", raising=False)

    assert constants.resource_path("app_icon.ico") == r"C:\bundle\app_icon.ico"
