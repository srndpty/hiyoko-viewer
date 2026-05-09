import runpy


def test_main_can_be_imported_without_starting_application() -> None:
    namespace = runpy.run_module("main", run_name="imported_for_test")

    assert "ImageViewer" in namespace
    assert "QApplication" in namespace
