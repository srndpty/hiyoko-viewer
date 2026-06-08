import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from hiyoko_viewer.ui.dialogs import metadata_dialog as widgets
from hiyoko_viewer.ui.dialogs.metadata_dialog import JsonHighlighter, MetadataDialog


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_metadata_dialog_initializes_text_and_title(qapp, monkeypatch) -> None:
    monkeypatch.setattr(widgets.QFontDatabase, "families", lambda: ["Consolas"])

    dialog = MetadataDialog("Title", '{"key": "value"}')

    assert dialog.windowTitle() == "Title"
    assert dialog.text_edit.toPlainText() == '{"key": "value"}'
    assert dialog.content_text == '{"key": "value"}'


def test_metadata_dialog_copy_to_clipboard(qapp, monkeypatch) -> None:
    monkeypatch.setattr(widgets.QFontDatabase, "families", lambda: [])
    dialog = MetadataDialog("Title", "copy me")

    dialog.copy_to_clipboard()

    assert qapp.clipboard().text() == "copy me"


def test_json_highlighter_builds_rules_for_json_tokens() -> None:
    highlighter = JsonHighlighter()

    patterns = [pattern.pattern for pattern, _format in highlighter.highlighting_rules]

    assert patterns == [
        r'"[^"]*"\s*:',
        r'"[^"]*"',
        r"\b-?\d+(\.\d+)?([eE][+-]?\d+)?\b",
        r"\b(true|false)\b",
        r"\bnull\b",
    ]
