"""メニューバーのアクセスキーと、既存操作へのショートカット割り当て。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from hiyoko_viewer.config.constants import NG_FOLDER, OK_FOLDER
from hiyoko_viewer.ui import main_window
from hiyoko_viewer.ui.main_window import ImageViewer, _numpad_sequence
from hiyoko_viewer.ui.mixins import navigation


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def viewer(qapp, monkeypatch):
    monkeypatch.setattr(ImageViewer, "_load_settings", lambda self: None)
    monkeypatch.setattr(ImageViewer, "_setup_worker_thread", lambda self: None)
    window = ImageViewer()
    window.show()
    qapp.setActiveWindow(window)
    window.activateWindow()
    window.scroll_area.setFocus()
    qapp.processEvents()
    yield window
    window.hide()
    window.deleteLater()
    qapp.processEvents()


def _mnemonics(actions) -> list[str]:
    found: list[str] = []
    for action in actions:
        text = action.text()
        mark = text.find("&")
        if mark >= 0 and mark + 1 < len(text):
            found.append(text[mark + 1].upper())
    return found


def _press(viewer: ImageViewer, key: Qt.Key, modifier=Qt.KeyboardModifier.NoModifier) -> None:
    QTest.keyClick(viewer.scroll_area, key, modifier)


def test_menu_bar_registers_commands_with_unique_mnemonics(viewer) -> None:
    titles = [action.text() for action in viewer.menuBar().actions()]
    assert titles == ["ファイル(&F)", "表示(&V)", "アニメーション(&A)"]
    top_keys = _mnemonics(viewer.menuBar().actions())
    assert len(top_keys) == len(set(top_keys))

    expected = {
        "ファイル(&F)": [
            "開く(&O)...",
            "_ok フォルダへ移動(&K)",
            "_ng フォルダへ移動(&N)",
            "ごみ箱へ移動(&D)",
            "トレイに格納(&T)",
            "終了(&X)",
        ],
        "表示(&V)": [
            "フィット表示(&F)",
            "フルスクリーン(&L)",
            "シャッフル(&S)",
            "メタデータ(&I)...",
            "次の画像(&N)",
            "前の画像(&P)",
        ],
        "アニメーション(&A)": [
            "再生/一時停止(&P)",
            "コマ送り(&S)",
        ],
    }
    for action in viewer.menuBar().actions():
        menu = action.menu()
        labels = [item.text() for item in menu.actions() if not item.isSeparator()]
        assert labels == expected[action.text()]
        keys = _mnemonics(menu.actions())
        assert len(keys) == len(set(keys))


def test_menu_shortcuts_match_existing_keys(viewer) -> None:
    assert viewer.open_action.shortcut() == QKeySequence("Ctrl+O")
    assert viewer.move_ok_action.shortcut() == _numpad_sequence(Qt.Key.Key_7)
    assert viewer.move_ng_action.shortcut() == _numpad_sequence(Qt.Key.Key_9)
    assert viewer.delete_action.shortcut() == QKeySequence(Qt.Key.Key_Delete)
    assert viewer.hide_to_tray_action.shortcut() == QKeySequence(Qt.Key.Key_Escape)
    assert viewer.quit_action.shortcut().isEmpty()
    assert viewer.fit_action.shortcut() == QKeySequence(Qt.Key.Key_F)
    assert viewer.fullscreen_action.shortcut() == QKeySequence(Qt.Key.Key_F11)
    assert viewer.shuffle_action.shortcut() == QKeySequence(Qt.Key.Key_R)
    assert viewer.metadata_action.shortcut() == QKeySequence(Qt.Key.Key_I)
    assert viewer.next_action.shortcuts() == [
        QKeySequence(Qt.Key.Key_Right),
        QKeySequence(Qt.Key.Key_PageDown),
    ]
    assert viewer.prev_action.shortcuts() == [
        QKeySequence(Qt.Key.Key_Left),
        QKeySequence(Qt.Key.Key_PageUp),
    ]
    assert viewer.play_pause_action.shortcut().isEmpty()
    assert viewer.step_frame_action.shortcut() == QKeySequence(Qt.Key.Key_Period)


def test_fit_shortcut_toggles_once_and_ignores_loading(viewer) -> None:
    viewer.fit_to_window = True
    viewer.is_loading = True
    _press(viewer, Qt.Key.Key_F)
    assert viewer.fit_to_window is True

    viewer.is_loading = False
    _press(viewer, Qt.Key.Key_F)
    assert viewer.fit_to_window is False


def test_arrow_shortcut_advances_one_image(viewer) -> None:
    calls: list[str] = []
    viewer.image_files = ["a.png", "b.png"]
    viewer.current_index = 0
    viewer.is_loading = False
    viewer.load_image_by_index = lambda: calls.append("load")

    _press(viewer, Qt.Key.Key_Right)
    assert viewer.current_index == 1
    assert calls == ["load"]

    _press(viewer, Qt.Key.Key_PageUp)
    assert viewer.current_index == 0
    assert calls == ["load", "load"]


def test_numpad_shortcut_moves_to_ok_and_plain_digit_does_not(
    viewer, tmp_path, monkeypatch
) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(b"x")
    moved: list[tuple[str, str]] = []
    monkeypatch.setattr(navigation.shutil, "move", lambda src, dest: moved.append((src, dest)))
    viewer.image_files = [str(image)]
    viewer.sorted_image_files = [str(image)]
    viewer.current_index = 0
    viewer.is_loading = False

    _press(viewer, Qt.Key.Key_7)
    assert moved == []

    _press(viewer, Qt.Key.Key_7, Qt.KeyboardModifier.KeypadModifier)
    assert moved == [(str(image), str(tmp_path / OK_FOLDER))]


def test_numpad_9_moves_to_ng(viewer, tmp_path, monkeypatch) -> None:
    image = tmp_path / "b.png"
    image.write_bytes(b"x")
    moved: list[tuple[str, str]] = []
    monkeypatch.setattr(navigation.shutil, "move", lambda src, dest: moved.append((src, dest)))
    viewer.image_files = [str(image)]
    viewer.sorted_image_files = [str(image)]
    viewer.current_index = 0
    viewer.is_loading = False

    _press(viewer, Qt.Key.Key_9, Qt.KeyboardModifier.KeypadModifier)
    assert moved == [(str(image), str(tmp_path / NG_FOLDER))]


def test_delete_shortcut_sends_file_to_trash(viewer, tmp_path, monkeypatch) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(b"x")
    trashed: list[str] = []
    monkeypatch.setattr(navigation, "send2trash", trashed.append)
    viewer.image_files = [str(image)]
    viewer.sorted_image_files = [str(image)]
    viewer.current_index = 0
    viewer.is_loading = False

    _press(viewer, Qt.Key.Key_Delete)
    assert trashed == [str(image)]


def test_metadata_shortcut_opens_dialog(viewer, monkeypatch) -> None:
    opened: list[str] = []

    class _Dialog:
        def __init__(self, title: str, content: str, parent) -> None:
            del content, parent
            opened.append(title)

        def exec(self) -> None:
            opened.append("exec")

    monkeypatch.setattr(main_window, "MetadataDialog", _Dialog)
    monkeypatch.setattr(main_window, "load_metadata_text", lambda path: "meta")
    viewer.image_files = [r"C:\images\a.png"]
    viewer.current_index = 0
    viewer.is_loading = True
    _press(viewer, Qt.Key.Key_I)
    assert opened == []

    viewer.is_loading = False
    _press(viewer, Qt.Key.Key_I)
    assert opened == ["メタデータ: a.png", "exec"]


def test_shuffle_shortcut_toggles_once(viewer) -> None:
    viewer.image_files = ["a.png", "b.png"]
    viewer.sorted_image_files = ["a.png", "b.png"]
    viewer.current_index = 0
    viewer.is_shuffled = False
    viewer.is_loading = False
    viewer.load_image_by_index = lambda: None

    _press(viewer, Qt.Key.Key_R)
    assert viewer.is_shuffled is True


def test_step_and_playback_actions(viewer) -> None:
    from PyQt6.QtGui import QMovie

    class _Movie:
        def __init__(self) -> None:
            self.jumped: list[int] = []
            self.paused: list[bool] = []

        def isValid(self) -> bool:
            return True

        def frameCount(self) -> int:
            return 4

        def currentFrameNumber(self) -> int:
            return 1

        def jumpToFrame(self, frame: int) -> None:
            self.jumped.append(frame)

        def setPaused(self, paused: bool) -> None:
            self.paused.append(paused)

        def state(self) -> QMovie.MovieState:
            return QMovie.MovieState.Running

    movie = _Movie()
    viewer.current_movie = movie
    viewer.is_loading = False

    _press(viewer, Qt.Key.Key_Period)
    assert movie.jumped == [2]
    assert movie.paused == [True]

    viewer.play_pause_action.trigger()
    assert movie.paused == [True, True]


def test_escape_while_loading_keeps_the_window(viewer) -> None:
    viewer.is_loading = True
    _press(viewer, Qt.Key.Key_Escape)
    assert viewer.isVisible() is True


def test_quit_action_asks_the_application_to_exit(viewer, monkeypatch) -> None:
    calls: list[str] = []

    class _App:
        def quit(self) -> None:
            calls.append("quit")

    monkeypatch.setattr(main_window.QApplication, "instance", staticmethod(lambda: _App()))
    viewer.quit_action.trigger()
    assert calls == ["quit"]

    monkeypatch.setattr(main_window.QApplication, "instance", staticmethod(lambda: None))
    viewer.quit_action.trigger()
    assert calls == ["quit"]


def test_escape_hides_to_tray_and_fullscreen_toggles_once(viewer) -> None:
    _press(viewer, Qt.Key.Key_F11)
    assert viewer.isFullScreen()
    _press(viewer, Qt.Key.Key_F11)
    assert viewer.isFullScreen() is False

    assert viewer.isVisible()
    _press(viewer, Qt.Key.Key_Escape)
    assert viewer.isVisible() is False
