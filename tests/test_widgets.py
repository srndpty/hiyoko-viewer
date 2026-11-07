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


def test_metadata_dialog_hides_strip_button_without_handler(qapp) -> None:
    dialog = MetadataDialog("Title", "text")

    assert dialog.strip_button is None


def test_metadata_dialog_strip_button_calls_handler(qapp) -> None:
    calls: list[str] = []
    dialog = MetadataDialog("Title", "before", strip_handler=lambda: calls.append("strip"))

    dialog.strip_button.click()

    assert calls == ["strip"]


def test_metadata_dialog_set_content_updates_text(qapp) -> None:
    dialog = MetadataDialog("Title", "before", strip_handler=lambda: None)

    dialog.set_content("after")

    assert dialog.text_edit.toPlainText() == "after"
    assert dialog.content_text == "after"


def test_metadata_dialog_busy_blocks_buttons_and_closing(qapp) -> None:
    calls: list[str] = []
    dialog = MetadataDialog("Title", "text", strip_handler=lambda: calls.append("strip"))
    dialog.show()

    dialog.set_busy(True)
    dialog.strip_metadata()
    dialog.reject()

    assert calls == []
    assert not dialog.button_box.isEnabled()
    assert dialog.isVisible()

    dialog.set_busy(False)
    assert dialog.button_box.isEnabled()
    dialog.reject()
    assert not dialog.isVisible()


def test_metadata_dialog_disables_strip_button_with_reason(qapp) -> None:
    dialog = MetadataDialog(
        "Title", "text", strip_handler=lambda: None, strip_disabled_reason="未対応です"
    )

    assert not dialog.strip_button.isEnabled()
    assert dialog.strip_button.toolTip() == "未対応です"


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
