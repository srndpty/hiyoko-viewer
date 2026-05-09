import runpy
import sys
import types


class _FakeFormat:
    def __init__(self, name: str) -> None:
        self._name = name

    def data(self) -> bytes:
        return self._name.encode()


class _FakeApplication:
    def __init__(self, argv: list[str]) -> None:
        self.argv = argv


class _FakeImageReader:
    @staticmethod
    def supportedImageFormats() -> list[_FakeFormat]:
        return [_FakeFormat("png"), _FakeFormat("webp")]


def test_check_formats_prints_supported_formats(monkeypatch, capsys) -> None:
    pyqt_module = types.ModuleType("PyQt6")
    qt_widgets_module = types.ModuleType("PyQt6.QtWidgets")
    qt_gui_module = types.ModuleType("PyQt6.QtGui")
    qt_widgets_module.QApplication = _FakeApplication
    qt_gui_module.QImageReader = _FakeImageReader
    monkeypatch.setitem(sys.modules, "PyQt6", pyqt_module)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qt_widgets_module)
    monkeypatch.setitem(sys.modules, "PyQt6.QtGui", qt_gui_module)

    runpy.run_module("check_formats", run_name="__main__")

    output = capsys.readouterr().out
    assert "PyQt6がサポートしている画像フォーマット" in output
    assert "'.png', '.webp'" in output
