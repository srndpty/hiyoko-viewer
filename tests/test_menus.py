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


def _arm(viewer: ImageViewer, files: list[str], *, movie: object | None = None) -> None:
    """画像がある状態にしてからメニューの有効状態を合わせる。"""
    viewer.image_files = files
    viewer.sorted_image_files = list(files)
    viewer.current_index = 0
    viewer.current_movie = movie
    viewer.is_loading = False
    viewer._sync_action_states()


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
    _arm(viewer, ["a.png"])
    viewer.fit_to_window = True
    viewer.is_loading = True
    viewer._sync_action_states()
    assert viewer.fit_action.isEnabled() is False
    _press(viewer, Qt.Key.Key_F)
    # ショートカットが無効でも、メソッドを直接呼んだときのガードは残す
    ImageViewer._toggle_fit_mode(viewer)
    assert viewer.fit_to_window is True

    viewer.is_loading = False
    viewer._sync_action_states()
    assert viewer.fit_action.isEnabled() is True
    _press(viewer, Qt.Key.Key_F)
    assert viewer.fit_to_window is False


def test_arrow_and_page_keys_navigate_instead_of_scrolling(viewer) -> None:
    calls: list[str] = []
    _arm(viewer, ["a.png", "b.png", "c.png"])
    viewer.load_image_by_index = lambda: calls.append("load")
    viewer.image_label.setMinimumSize(4000, 4000)
    horizontal = viewer.scroll_area.horizontalScrollBar()
    vertical = viewer.scroll_area.verticalScrollBar()
    horizontal.setValue(15)
    vertical.setValue(25)

    _press(viewer, Qt.Key.Key_Right)
    _press(viewer, Qt.Key.Key_Left)
    _press(viewer, Qt.Key.Key_PageDown)
    _press(viewer, Qt.Key.Key_PageUp)

    assert calls == ["load", "load", "load", "load"]
    assert viewer.current_index == 0
    assert horizontal.value() == 15
    assert vertical.value() == 25


def test_numpad_shortcut_moves_to_ok_and_plain_digit_does_not(
    viewer, tmp_path, monkeypatch
) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(b"x")
    moved: list[tuple[str, str]] = []
    monkeypatch.setattr(navigation.shutil, "move", lambda src, dest: moved.append((src, dest)))
    _arm(viewer, [str(image)])

    _press(viewer, Qt.Key.Key_7)
    _press(viewer, Qt.Key.Key_Home, Qt.KeyboardModifier.KeypadModifier)
    assert moved == []

    _press(viewer, Qt.Key.Key_7, Qt.KeyboardModifier.KeypadModifier)
    assert moved == [(str(image), str(tmp_path / OK_FOLDER))]


def test_numpad_9_moves_to_ng(viewer, tmp_path, monkeypatch) -> None:
    image = tmp_path / "b.png"
    image.write_bytes(b"x")
    moved: list[tuple[str, str]] = []
    monkeypatch.setattr(navigation.shutil, "move", lambda src, dest: moved.append((src, dest)))
    _arm(viewer, [str(image)])
    viewer.load_image_by_index = lambda: None

    _press(viewer, Qt.Key.Key_9)
    _press(viewer, Qt.Key.Key_PageUp, Qt.KeyboardModifier.KeypadModifier)
    assert moved == []
    assert viewer.current_index == 0

    _press(viewer, Qt.Key.Key_9, Qt.KeyboardModifier.KeypadModifier)
    assert moved == [(str(image), str(tmp_path / NG_FOLDER))]


def test_delete_shortcut_sends_file_to_trash(viewer, tmp_path, monkeypatch) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(b"x")
    trashed: list[str] = []
    monkeypatch.setattr(navigation, "send2trash", trashed.append)
    _arm(viewer, [str(image)])

    _press(viewer, Qt.Key.Key_Delete)
    assert trashed == [str(image)]
    assert viewer.delete_action.isEnabled() is False
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
    _arm(viewer, [r"C:\images\a.png"])
    viewer.is_loading = True
    viewer._sync_action_states()
    _press(viewer, Qt.Key.Key_I)
    ImageViewer.show_metadata_dialog(viewer)
    assert opened == []

    viewer.is_loading = False
    viewer._sync_action_states()
    _press(viewer, Qt.Key.Key_I)
    assert opened == ["メタデータ: a.png", "exec"]


def test_shuffle_shortcut_toggles_once(viewer) -> None:
    _arm(viewer, ["a.png", "b.png"])
    viewer.is_shuffled = False
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
    _arm(viewer, ["animation.gif"], movie=movie)

    _press(viewer, Qt.Key.Key_Period)
    assert movie.jumped == [2]
    assert movie.paused == [True]

    viewer.play_pause_action.trigger()
    assert movie.paused == [True, True]


def test_escape_while_loading_keeps_the_window(viewer) -> None:
    viewer.is_loading = True
    _press(viewer, Qt.Key.Key_Escape)
    assert viewer.isVisible() is True


def test_menu_actions_follow_loading_image_and_movie(viewer) -> None:
    image_actions = (
        viewer.move_ok_action,
        viewer.move_ng_action,
        viewer.delete_action,
        viewer.next_action,
        viewer.prev_action,
        viewer.shuffle_action,
        viewer.metadata_action,
        viewer.fit_action,
    )
    always_on = (
        viewer.open_action,
        viewer.hide_to_tray_action,
        viewer.quit_action,
        viewer.fullscreen_action,
    )
    assert all(action.isEnabled() is False for action in image_actions)
    assert viewer.play_pause_action.isEnabled() is False
    assert viewer.step_frame_action.isEnabled() is False
    assert all(action.isEnabled() is True for action in always_on)

    _arm(viewer, ["a.png"])
    assert all(action.isEnabled() is True for action in image_actions)
    assert viewer.play_pause_action.isEnabled() is False

    viewer.is_loading = True
    viewer._sync_action_states()
    assert all(action.isEnabled() is False for action in image_actions)
    assert all(action.isEnabled() is True for action in always_on)

    class _Movie:
        def isValid(self) -> bool:
            return True

    viewer.is_loading = False
    viewer.current_movie = _Movie()
    viewer._sync_action_states()
    assert viewer.play_pause_action.isEnabled() is True
    assert viewer.step_frame_action.isEnabled() is True


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


def test_escape_hides_from_fullscreen_and_from_normal(viewer) -> None:
    _press(viewer, Qt.Key.Key_F11)
    assert viewer.isFullScreen() is True
    _press(viewer, Qt.Key.Key_Escape)
    assert viewer.isVisible() is False

    viewer.showNormal()
    assert viewer.isFullScreen() is False
    assert viewer.isVisible() is True
    _press(viewer, Qt.Key.Key_Escape)
    assert viewer.isVisible() is False


def test_image_load_disables_actions_until_the_image_arrives(viewer, tmp_path) -> None:
    from PIL import Image
    from PyQt6.QtGui import QImage

    path = tmp_path / "still.png"
    Image.new("RGB", (2, 2), (10, 20, 30)).save(path)
    _arm(viewer, [str(path)])
    assert viewer.delete_action.isEnabled() is True

    viewer.load_image_by_index()
    assert viewer.is_loading is True
    assert viewer.delete_action.isEnabled() is False

    viewer.update_image_display(viewer._load_generation, str(path), QImage(str(path)))
    assert viewer.is_loading is False
    assert viewer.next_action.isEnabled() is True
    assert viewer.step_frame_action.isEnabled() is False


def test_period_steps_one_frame_for_gif_webp_and_apng(viewer, tmp_path) -> None:
    from PIL import Image
    from PyQt6.QtGui import QMovie

    from hiyoko_viewer.ui.apng_movie import ApngMovie

    frames = [Image.new("RGBA", (2, 2), color) for color in ((255, 0, 0, 255), (0, 255, 0, 255))]
    cases = (
        ("GIF", tmp_path / "anim.gif", QMovie),
        ("WEBP", tmp_path / "anim.webp", QMovie),
        ("PNG", tmp_path / "anim.png", ApngMovie),
    )
    for fmt, path, factory in cases:
        frames[0].save(
            path, save_all=True, append_images=frames[1:], duration=40, loop=0, format=fmt
        )
        movie = factory(str(path))
        assert movie.isValid() is True
        assert movie.frameCount() >= 2
        movie.start()
        assert movie.jumpToFrame(0) is not False
        start = movie.currentFrameNumber()
        _arm(viewer, [str(path)], movie=movie)

        _press(viewer, Qt.Key.Key_Period)

        assert movie.currentFrameNumber() == (start + 1) % movie.frameCount()
        assert movie.state() == QMovie.MovieState.Paused
