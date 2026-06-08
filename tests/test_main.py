import runpy


def test_app_module_can_be_imported_without_starting_application() -> None:
    namespace = runpy.run_module("hiyoko_viewer.app", run_name="imported_for_test")

    assert "ImageViewer" in namespace
    assert "QApplication" in namespace
    assert callable(namespace["main"])
