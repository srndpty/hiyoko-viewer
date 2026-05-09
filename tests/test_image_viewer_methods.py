import os
from types import SimpleNamespace

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMovie

import image_viewer
from constants import OK_FOLDER
from image_viewer import ImageViewer


class _ScrollBar:
    def __init__(self, value: int = 0) -> None:
        self._value = value

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self._value = value


class _ScrollArea:
    def __init__(self) -> None:
        self.horizontal = _ScrollBar(100)
        self.vertical = _ScrollBar(200)

    def horizontalScrollBar(self) -> _ScrollBar:
        return self.horizontal

    def verticalScrollBar(self) -> _ScrollBar:
        return self.vertical


class _WheelEvent:
    def __init__(self, modifiers: Qt.KeyboardModifier) -> None:
        self._modifiers = modifiers

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def angleDelta(self) -> SimpleNamespace:
        return SimpleNamespace(y=lambda: 120)


class _Movie:
    def __init__(self, state: QMovie.MovieState = QMovie.MovieState.Running) -> None:
        self._state = state
        self.paused_values: list[bool] = []
        self.jumped_to: list[int] = []

    def isValid(self) -> bool:
        return True

    def state(self) -> QMovie.MovieState:
        return self._state

    def setPaused(self, paused: bool) -> None:
        self.paused_values.append(paused)
        self._state = QMovie.MovieState.Paused if paused else QMovie.MovieState.Running

    def frameCount(self) -> int:
        return 3

    def currentFrameNumber(self) -> int:
        return 1

    def jumpToFrame(self, frame: int) -> None:
        self.jumped_to.append(frame)


class _Emitter:
    def __init__(self) -> None:
        self.emitted: list[tuple] = []

    def emit(self, *args) -> None:
        self.emitted.append(args)


class _StatusBar:
    def __init__(self) -> None:
        self.messages: list[tuple] = []
        self.cleared = False

    def showMessage(self, message: str, timeout: int | None = None) -> None:
        self.messages.append((message, timeout))

    def clearMessage(self) -> None:
        self.cleared = True


class _ImageLabel:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def setText(self, text: str) -> None:
        self.texts.append(text)


class _Viewport:
    def size(self) -> SimpleNamespace:
        return SimpleNamespace(width=lambda: 400, height=lambda: 200)


class _ScrollAreaWithViewport:
    def viewport(self) -> _Viewport:
        return _Viewport()


class _Pixmap:
    def __init__(self, width: int = 200, height: int = 100, is_null: bool = False) -> None:
        self._width = width
        self._height = height
        self._is_null = is_null

    def isNull(self) -> bool:
        return self._is_null

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


def test_show_next_image_advances_and_loads() -> None:
    loaded_indices: list[int] = []
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=["a.png", "b.png"],
        current_index=0,
    )
    viewer.load_image_by_index = lambda: loaded_indices.append(viewer.current_index)

    ImageViewer.show_next_image(viewer)

    assert viewer.current_index == 1
    assert loaded_indices == [1]


def test_show_prev_image_wraps_and_loads() -> None:
    loaded_indices: list[int] = []
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=["a.png", "b.png"],
        current_index=0,
    )
    viewer.load_image_by_index = lambda: loaded_indices.append(viewer.current_index)

    ImageViewer.show_prev_image(viewer)

    assert viewer.current_index == 1
    assert loaded_indices == [1]


def test_navigation_ignores_loading_state() -> None:
    viewer = SimpleNamespace(is_loading=True, image_files=["a.png"], current_index=0)
    viewer.load_image_by_index = lambda: (_ for _ in ()).throw(AssertionError("should not load"))

    ImageViewer.show_next_image(viewer)
    ImageViewer.show_prev_image(viewer)

    assert viewer.current_index == 0


def test_toggle_fit_mode_updates_zoom_and_redraws() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(fit_to_window=True, scale_factor=2.0)
    viewer.redraw_image = lambda: calls.append("redraw")
    viewer.update_status_bar = lambda: calls.append("status")

    ImageViewer._toggle_fit_mode(viewer)

    assert viewer.fit_to_window is False
    assert viewer.scale_factor == 1.0
    assert calls == ["redraw", "status"]


def test_toggle_shuffle_mode_can_restore_sorted_order() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(
        image_files=["b.png", "a.png"],
        sorted_image_files=["a.png", "b.png"],
        current_index=0,
        is_shuffled=True,
    )
    viewer.update_status_bar = lambda: calls.append("status")

    ImageViewer._toggle_shuffle_mode(viewer)

    assert viewer.is_shuffled is False
    assert viewer.image_files == ["a.png", "b.png"]
    assert viewer.current_index == 1
    assert calls == ["status"]


def test_scroll_image_moves_vertical_and_horizontal_scrollbars() -> None:
    viewer = SimpleNamespace(scroll_area=_ScrollArea())

    ImageViewer._scroll_image(viewer, _WheelEvent(Qt.KeyboardModifier.NoModifier))
    ImageViewer._scroll_image(viewer, _WheelEvent(Qt.KeyboardModifier.ShiftModifier))

    assert viewer.scroll_area.verticalScrollBar().value() == 160
    assert viewer.scroll_area.horizontalScrollBar().value() == 60


def test_toggle_gif_playback_pauses_and_resumes_movie() -> None:
    calls: list[str] = []
    movie = _Movie()
    viewer = SimpleNamespace(current_movie=movie)
    viewer.update_status_bar = lambda: calls.append("status")

    assert ImageViewer._toggle_gif_playback(viewer) is True
    assert ImageViewer._toggle_gif_playback(viewer) is True

    assert movie.paused_values == [True, False]
    assert calls == ["status", "status"]


def test_toggle_gif_playback_returns_false_without_movie() -> None:
    viewer = SimpleNamespace(current_movie=None)

    assert ImageViewer._toggle_gif_playback(viewer) is False


def test_step_gif_frame_advances_and_pauses() -> None:
    calls: list[str] = []
    movie = _Movie()
    viewer = SimpleNamespace(current_movie=movie)
    viewer.update_status_bar = lambda: calls.append("status")

    ImageViewer._step_gif_frame(viewer, Qt.Key.Key_Period)

    assert movie.jumped_to == [2]
    assert movie.paused_values == [True]
    assert calls == ["status"]


def test_load_image_from_path_requests_directory_scan(tmp_path) -> None:
    emitter = _Emitter()
    calls: list[str] = []
    image_path = tmp_path / "Photo.PNG"
    viewer = SimpleNamespace(request_load_list=emitter)
    viewer._clear_display = lambda: calls.append("clear")

    ImageViewer.load_image_from_path(viewer, str(image_path))

    assert calls == ["clear"]
    assert emitter.emitted == [(str(tmp_path), os.path.normcase(os.path.normpath(str(image_path))))]


def test_load_image_from_path_ignores_empty_path() -> None:
    viewer = SimpleNamespace()
    viewer._clear_display = lambda: (_ for _ in ()).throw(AssertionError("should not clear"))

    ImageViewer.load_image_from_path(viewer, "")


def test_on_file_list_loaded_sets_error_text_for_empty_list() -> None:
    label = _ImageLabel()
    viewer = SimpleNamespace(image_label=label)

    ImageViewer.on_file_list_loaded(viewer, [], -1)

    assert label.texts == ["画像の読み込みに失敗しました。"]


def test_on_file_list_loaded_sorts_and_keeps_selected_file(monkeypatch) -> None:
    loaded: list[int] = []
    monkeypatch.setattr(image_viewer, "windows_logical_key", lambda path: path)
    viewer = SimpleNamespace(
        sorted_image_files=[],
        image_files=[],
        is_shuffled=True,
        current_index=-1,
    )
    viewer.load_image_by_index = lambda: loaded.append(viewer.current_index)

    ImageViewer.on_file_list_loaded(viewer, ["b.png", "a.png"], 0)

    assert viewer.sorted_image_files == ["a.png", "b.png"]
    assert viewer.image_files == ["a.png", "b.png"]
    assert viewer.is_shuffled is False
    assert viewer.current_index == 1
    assert loaded == [1]


def test_load_image_by_index_emits_current_file(tmp_path) -> None:
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"fake image")
    status_bar = _StatusBar()
    emitter = _Emitter()
    titles: list[str] = []
    viewer = SimpleNamespace(
        is_loading=False,
        current_index=0,
        image_files=[str(image_path)],
        fit_to_window=False,
        scale_factor=3.0,
        current_filesize=0,
        request_load_image=emitter,
    )
    viewer.windowTitle = lambda: "Window"
    viewer.setWindowTitle = titles.append
    viewer.statusBar = lambda: status_bar

    ImageViewer.load_image_by_index(viewer)

    assert viewer.fit_to_window is True
    assert viewer.scale_factor == 1.0
    assert viewer.is_loading is True
    assert viewer.current_filesize == len(b"fake image")
    assert titles == ["Window | 読み込み中..."]
    assert status_bar.messages == [("読み込み中...", None)]
    assert emitter.emitted == [(str(image_path),)]


def test_move_current_image_and_load_next_moves_to_subfolder(tmp_path) -> None:
    image_path = tmp_path / "a.png"
    next_path = tmp_path / "b.png"
    image_path.write_bytes(b"fake")
    next_path.write_bytes(b"fake")
    loaded: list[int] = []
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=[str(image_path), str(next_path)],
        current_index=0,
    )
    viewer.load_image_by_index = lambda: loaded.append(viewer.current_index)
    viewer._clear_display = lambda: loaded.append(-1)

    ImageViewer.move_current_image_and_load_next(viewer, OK_FOLDER)

    assert (tmp_path / OK_FOLDER / "a.png").exists()
    assert viewer.image_files == [str(next_path)]
    assert loaded == [0]


def test_delete_current_image_and_load_next_uses_send2trash(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "a.png"
    next_path = tmp_path / "b.png"
    trashed: list[str] = []
    loaded: list[int] = []
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=[str(image_path), str(next_path)],
        current_index=0,
    )
    viewer.load_image_by_index = lambda: loaded.append(viewer.current_index)
    viewer._clear_display = lambda: loaded.append(-1)
    monkeypatch.setattr(image_viewer, "send2trash", trashed.append)

    ImageViewer.delete_current_image_and_load_next(viewer)

    assert trashed == [str(image_path)]
    assert viewer.image_files == [str(next_path)]
    assert loaded == [0]


def test_update_status_bar_shows_static_image_details() -> None:
    status_bar = _StatusBar()
    viewer = SimpleNamespace(
        original_pixmap=_Pixmap(),
        current_filesize=1024 * 1024,
        fit_to_window=True,
        scroll_area=_ScrollAreaWithViewport(),
        is_shuffled=False,
        current_movie=None,
    )
    viewer.statusBar = lambda: status_bar

    ImageViewer.update_status_bar(viewer)

    assert status_bar.messages == [("🖼️ 200x100  |  💾 1.00MB  |  ↕️ 200.0%", None)]


def test_update_status_bar_clears_message_without_pixmap() -> None:
    status_bar = _StatusBar()
    viewer = SimpleNamespace(original_pixmap=_Pixmap(is_null=True))
    viewer.statusBar = lambda: status_bar

    ImageViewer.update_status_bar(viewer)

    assert status_bar.cleared is True
