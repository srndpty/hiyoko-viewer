import importlib


def test_app_module_can_be_imported_without_starting_application() -> None:
    module = importlib.import_module("hiyoko_viewer.app")

    assert module.ImageViewer is not None
    assert module.QApplication is not None
    assert callable(module.main)
