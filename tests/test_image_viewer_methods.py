import os
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QMovie

from hiyoko_viewer.config import constants
from hiyoko_viewer.config.constants import OK_FOLDER
from hiyoko_viewer.ui import main_window
from hiyoko_viewer.ui.main_window import ImageViewer
from hiyoko_viewer.ui.mixins import input as input_events
from hiyoko_viewer.ui.mixins import navigation, rendering


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
    def __init__(
        self,
        modifiers: Qt.KeyboardModifier,
        delta: int = 120,
        position: object | None = None,
    ) -> None:
        self._modifiers = modifiers
        self._delta = delta
        self._position = position or _Point(10, 20)

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def angleDelta(self) -> SimpleNamespace:
        return SimpleNamespace(y=lambda: self._delta)

    def position(self) -> object:
        return self._position


class _Point:
    def __init__(self, x: int, y: int) -> None:
        self._x = x
        self._y = y

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y

    def __sub__(self, other: "_Point") -> "_Point":
        return _Point(self._x - other._x, self._y - other._y)


class _MouseEvent:
    def __init__(self, button: Qt.MouseButton = Qt.MouseButton.LeftButton) -> None:
        self._button = button
        self._position = _Point(10, 20)

    def button(self) -> Qt.MouseButton:
        return self._button

    def position(self) -> _Point:
        return self._position


class _KeyEvent:
    def __init__(
        self,
        key: Qt.Key,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
        auto_repeat: bool = False,
    ) -> None:
        self._key = key
        self._modifiers = modifiers
        self._auto_repeat = auto_repeat
        self.ignored = False

    def key(self) -> Qt.Key:
        return self._key

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def isAutoRepeat(self) -> bool:
        return self._auto_repeat

    def ignore(self) -> None:
        self.ignored = True


class _Movie:
    def __init__(self, state: QMovie.MovieState = QMovie.MovieState.Running) -> None:
        self._state = state
        self.paused_values: list[bool] = []
        self.jumped_to: list[int] = []
        self.stopped = False
        self.started = False
        self.frameChanged = SimpleNamespace(
            connect=lambda *args: None,
            disconnect=lambda *args: None,
        )

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

    def stop(self) -> None:
        self.stopped = True

    def start(self) -> None:
        self.started = True

    def currentPixmap(self) -> "_Pixmap":
        return _Pixmap()


class _Emitter:
    def __init__(self) -> None:
        self.emitted: list[tuple] = []

    def emit(self, *args) -> None:
        self.emitted.append(args)


class _FrameProgress:
    def __init__(self) -> None:
        self.values: list[tuple[int, int]] = []

    def set_progress(self, current: int, total: int) -> None:
        self.values.append((current, total))


class _FrameLabel:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.visible: bool | None = None

    def setText(self, text: str) -> None:
        self.texts.append(text)

    def clear(self) -> None:
        self.texts.append("")

    def setVisible(self, visible: bool) -> None:
        self.visible = visible


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
        self.movies: list[object | None] = []
        self.scaled_contents_values: list[bool] = []
        self.fixed_sizes: list[object] = []
        self.pixmaps: list[object] = []
        self.adjusted = False
        self.minimum_sizes: list[tuple[int, int]] = []
        self.maximum_sizes: list[tuple[int, int]] = []
        self.styles: list[str] = []

    def setText(self, text: str) -> None:
        self.texts.append(text)

    def setMovie(self, movie: object | None) -> None:
        self.movies.append(movie)

    def setScaledContents(self, value: bool) -> None:
        self.scaled_contents_values.append(value)

    def setFixedSize(self, size: object) -> None:
        self.fixed_sizes.append(size)

    def movie(self) -> object | None:
        return self.movies[-1] if self.movies else None

    def setMinimumSize(self, width: int, height: int) -> None:
        self.minimum_sizes.append((width, height))

    def setMaximumSize(self, width: int, height: int) -> None:
        self.maximum_sizes.append((width, height))

    def setPixmap(self, pixmap: object) -> None:
        self.pixmaps.append(pixmap)

    def adjustSize(self) -> None:
        self.adjusted = True

    def setStyleSheet(self, style: str) -> None:
        self.styles.append(style)

    def clear(self) -> None:
        self.cleared = True


class _Viewport:
    def size(self) -> SimpleNamespace:
        return SimpleNamespace(width=lambda: 400, height=lambda: 200)


class _ScrollAreaWithViewport:
    def __init__(self) -> None:
        self.widget_resizable_values: list[bool] = []
        self.horizontal = _ScrollBar(100)
        self.vertical = _ScrollBar(200)

    def viewport(self) -> _Viewport:
        return _Viewport()

    def setWidgetResizable(self, value: bool) -> None:
        self.widget_resizable_values.append(value)

    def horizontalScrollBar(self) -> _ScrollBar:
        return self.horizontal

    def verticalScrollBar(self) -> _ScrollBar:
        return self.vertical


class _Size:
    def __init__(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def __mul__(self, factor: float) -> "_Size":
        return _Size(int(self._width * factor), int(self._height * factor))


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

    def size(self) -> _Size:
        return _Size(self._width, self._height)

    def scaled(self, *args) -> "_Pixmap":
        if args and isinstance(args[0], _Size):
            return _Pixmap(args[0].width(), args[0].height())
        if len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
            return _Pixmap(args[0], args[1])
        return _Pixmap(self._width, self._height)


class _FakeQPixmap:
    """worker からの QImage を GUI スレッドで変換する経路の代用。

    update_image_display 内の ``QPixmap.fromImage(image)`` を恒等変換にして、
    実 GUI リソースを使わずに静止画ロード経路を検証できるようにする。
    """

    @staticmethod
    def fromImage(image):
        return image


class _ImageContext:
    def __init__(self, *, is_animated: bool, n_frames: int) -> None:
        self.is_animated = is_animated
        self.n_frames = n_frames

    def __enter__(self) -> "_ImageContext":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _Settings:
    values: dict[str, object] = {}
    written: dict[str, object] = {}

    def __init__(self, organization: str, application: str) -> None:
        self.organization = organization
        self.application = application

    def value(self, key: str, default=None, type=None):
        return self.values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self.written[key] = value


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

    ImageViewer._step_gif_frame(viewer)

    assert movie.jumped_to == [2]
    assert movie.paused_values == [True]
    assert calls == ["status"]


def test_load_image_from_path_requests_directory_scan(tmp_path) -> None:
    emitter = _Emitter()
    calls: list[str] = []
    image_path = tmp_path / "Photo.PNG"
    viewer = SimpleNamespace(request_load_list=emitter, _load_generation=0)
    viewer._clear_display = lambda: calls.append("clear")

    ImageViewer.load_image_from_path(viewer, str(image_path))

    assert calls == ["clear"]
    assert viewer._load_generation == 1
    assert emitter.emitted == [
        (1, str(tmp_path), os.path.normcase(os.path.normpath(str(image_path))))
    ]


def test_load_image_from_path_normalizes_forward_slashes(tmp_path) -> None:
    # D&D / ファイルダイアログ由来の / 区切りパスでも、ワーカーにはネイティブ区切りで渡す
    emitter = _Emitter()
    image_path = tmp_path / "anim.png"
    viewer = SimpleNamespace(request_load_list=emitter, _load_generation=0)
    viewer._clear_display = lambda: None

    ImageViewer.load_image_from_path(viewer, str(image_path).replace(os.sep, "/"))

    assert emitter.emitted == [
        (1, os.path.normpath(str(tmp_path)), os.path.normcase(os.path.normpath(str(image_path))))
    ]


def test_load_image_from_path_ignores_empty_path() -> None:
    viewer = SimpleNamespace()
    viewer._clear_display = lambda: (_ for _ in ()).throw(AssertionError("should not clear"))

    ImageViewer.load_image_from_path(viewer, "")


def test_load_image_from_path_defers_recent_file_until_it_displays(tmp_path) -> None:
    emitter = _Emitter()
    remembered: list[str] = []
    image_path = tmp_path / "Photo.PNG"
    image_path.write_bytes(b"x")
    viewer = SimpleNamespace(request_load_list=emitter, _load_generation=0)
    viewer._clear_display = lambda: None
    viewer._remember_recent_file = remembered.append

    ImageViewer.load_image_from_path(viewer, str(image_path).replace(os.sep, "/"))

    assert remembered == []
    assert viewer._pending_recent_file == (1, os.path.normpath(str(image_path)))


def _viewer_waiting_to_record(path: str, generation: int = 1) -> SimpleNamespace:
    viewer = SimpleNamespace(
        image_files=[path],
        current_index=0,
        current_movie=None,
        image_label=_ImageLabel(),
        _load_generation=generation,
        _pending_recent_file=(generation, path),
        svg_renderer=None,
    )
    viewer.stop_movie = lambda: None
    viewer.redraw_image = lambda: None
    viewer.update_status_bar = lambda: None
    viewer.setWindowTitle = lambda title: None
    viewer._remember_recent_file = viewer_remembered(viewer).append
    viewer._commit_pending_recent_file = (
        lambda file_generation, file_path: ImageViewer._commit_pending_recent_file(
            viewer, file_generation, file_path
        )
    )
    viewer._drop_pending_recent_file = (
        lambda file_generation, file_path=None: ImageViewer._drop_pending_recent_file(
            viewer, file_generation, file_path
        )
    )
    return viewer


def viewer_remembered(viewer: SimpleNamespace) -> list[str]:
    remembered = getattr(viewer, "_remembered_paths", None)
    if remembered is None:
        remembered = []
        viewer._remembered_paths = remembered
    return remembered


def test_successful_display_records_the_pending_file(monkeypatch) -> None:
    path = "photo.png"
    viewer = _viewer_waiting_to_record(path)
    monkeypatch.setattr(rendering, "QPixmap", _FakeQPixmap)
    monkeypatch.setattr(rendering, "is_animated_png", lambda file_path: False)

    ImageViewer.update_image_display(viewer, 1, path, _Pixmap())

    assert viewer_remembered(viewer) == [path]
    assert viewer._pending_recent_file is None


def test_failed_display_does_not_record_the_pending_file(monkeypatch) -> None:
    path = "bad.webp"
    viewer = _viewer_waiting_to_record(path)
    monkeypatch.setattr(rendering, "QPixmap", _FakeQPixmap)

    ImageViewer.update_image_display(viewer, 1, path, _Pixmap(is_null=True))

    assert viewer_remembered(viewer) == []
    assert viewer._pending_recent_file is None


def test_stale_generation_does_not_record_the_pending_file() -> None:
    path = "photo.png"
    viewer = _viewer_waiting_to_record(path, generation=2)

    ImageViewer.update_image_display(viewer, 1, path, _Pixmap())

    assert viewer_remembered(viewer) == []
    assert viewer._pending_recent_file == (2, path)


def test_empty_file_list_drops_the_pending_recent_file() -> None:
    label = _ImageLabel()
    viewer = SimpleNamespace(
        image_label=label,
        _load_generation=3,
        _pending_recent_file=(3, "a.png"),
    )
    viewer._drop_pending_recent_file = (
        lambda generation, file_path=None: ImageViewer._drop_pending_recent_file(
            viewer, generation, file_path
        )
    )

    ImageViewer.on_file_list_loaded(viewer, 3, [], -1)

    assert label.texts == ["画像の読み込みに失敗しました。"]
    assert viewer._pending_recent_file is None


def test_show_next_image_does_not_record_a_recent_file() -> None:
    remembered: list[str] = []
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=["a.png", "b.png"],
        current_index=0,
    )
    viewer.load_image_by_index = lambda: None
    viewer._remember_recent_file = remembered.append

    ImageViewer.show_next_image(viewer)

    assert viewer.current_index == 1
    assert remembered == []


def test_on_file_list_loaded_sets_error_text_for_empty_list() -> None:
    label = _ImageLabel()
    viewer = SimpleNamespace(image_label=label, _load_generation=0)

    ImageViewer.on_file_list_loaded(viewer, 0, [], -1)

    assert label.texts == ["画像の読み込みに失敗しました。"]


def test_on_file_list_loaded_sorts_and_keeps_selected_file(monkeypatch) -> None:
    loaded: list[int] = []
    monkeypatch.setattr(navigation, "windows_logical_key", lambda path: path)
    viewer = SimpleNamespace(
        sorted_image_files=[],
        image_files=[],
        is_shuffled=True,
        current_index=-1,
        _load_generation=1,
    )
    viewer.load_image_by_index = lambda: loaded.append(viewer.current_index)

    ImageViewer.on_file_list_loaded(viewer, 1, ["b.png", "a.png"], 0)

    assert viewer.sorted_image_files == ["a.png", "b.png"]
    assert viewer.image_files == ["a.png", "b.png"]
    assert viewer.is_shuffled is False
    assert viewer.current_index == 1
    assert loaded == [1]


def test_on_file_list_loaded_ignores_stale_generation(monkeypatch) -> None:
    loaded: list[int] = []
    monkeypatch.setattr(navigation, "windows_logical_key", lambda path: path)
    viewer = SimpleNamespace(
        sorted_image_files=[],
        image_files=[],
        is_shuffled=False,
        current_index=-1,
        _load_generation=2,
    )
    viewer.load_image_by_index = lambda: loaded.append(viewer.current_index)

    # 世代 1 の結果が返ってきても、現在の世代 2 とは異なるので無視する
    ImageViewer.on_file_list_loaded(viewer, 1, ["a.png", "b.png"], 0)

    assert viewer.image_files == []
    assert loaded == []


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
        _load_generation=4,
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
    assert emitter.emitted == [(4, str(image_path))]


def test_move_current_image_and_load_next_moves_to_subfolder(tmp_path) -> None:
    image_path = tmp_path / "a.png"
    next_path = tmp_path / "b.png"
    image_path.write_bytes(b"fake")
    next_path.write_bytes(b"fake")
    loaded: list[int] = []
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=[str(image_path), str(next_path)],
        sorted_image_files=[str(image_path), str(next_path)],
        current_index=0,
        _release_current_file_handles=lambda: None,
    )
    viewer.load_image_by_index = lambda: loaded.append(viewer.current_index)
    viewer._clear_display = lambda: loaded.append(-1)
    viewer._remove_path_from_lists = lambda path: ImageViewer._remove_path_from_lists(viewer, path)

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
        sorted_image_files=[str(image_path), str(next_path)],
        current_index=0,
        _release_current_file_handles=lambda: None,
    )
    viewer.load_image_by_index = lambda: loaded.append(viewer.current_index)
    viewer._clear_display = lambda: loaded.append(-1)
    viewer._remove_path_from_lists = lambda path: ImageViewer._remove_path_from_lists(viewer, path)
    monkeypatch.setattr(navigation, "send2trash", trashed.append)

    ImageViewer.delete_current_image_and_load_next(viewer)

    assert trashed == [str(image_path)]
    assert viewer.image_files == [str(next_path)]
    assert loaded == [0]


def test_update_status_bar_shows_static_image_details() -> None:
    status_bar = _StatusBar()
    frame_progress = _FrameProgress()
    frame_label = _FrameLabel()
    viewer = SimpleNamespace(
        original_pixmap=_Pixmap(),
        current_filesize=1024 * 1024,
        fit_to_window=True,
        scroll_area=_ScrollAreaWithViewport(),
        is_shuffled=False,
        current_movie=None,
        frame_progress=frame_progress,
        frame_label=frame_label,
    )
    viewer.statusBar = lambda: status_bar

    ImageViewer.update_status_bar(viewer)

    assert status_bar.messages == [("🖼️ 200x100  |  💾 1.00MB  |  ↕️ 200.0%", None)]
    assert frame_progress.values == [(0, 0)]
    assert frame_label.texts == [""]
    assert frame_label.visible is False


def test_update_status_bar_clears_message_without_pixmap() -> None:
    status_bar = _StatusBar()
    frame_progress = _FrameProgress()
    viewer = SimpleNamespace(original_pixmap=_Pixmap(is_null=True), frame_progress=frame_progress)
    viewer.statusBar = lambda: status_bar

    ImageViewer.update_status_bar(viewer)

    assert status_bar.cleared is True
    assert frame_progress.values == [(0, 0)]


def test_load_image_by_index_ignores_invalid_index() -> None:
    viewer = SimpleNamespace(is_loading=False, current_index=2, image_files=["a.png"])
    viewer.request_load_image = _Emitter()

    ImageViewer.load_image_by_index(viewer)

    assert viewer.request_load_image.emitted == []


def test_load_image_by_index_uses_zero_filesize_for_missing_file(tmp_path) -> None:
    missing_path = tmp_path / "missing.png"
    status_bar = _StatusBar()
    emitter = _Emitter()
    titles: list[str] = []
    viewer = SimpleNamespace(
        is_loading=False,
        current_index=0,
        image_files=[str(missing_path)],
        request_load_image=emitter,
        _load_generation=4,
    )
    viewer.windowTitle = lambda: "Window"
    viewer.setWindowTitle = titles.append
    viewer.statusBar = lambda: status_bar

    ImageViewer.load_image_by_index(viewer)

    assert viewer.current_filesize == 0
    assert emitter.emitted == [(4, str(missing_path))]


def test_move_current_image_and_load_next_clears_when_last_file(tmp_path) -> None:
    image_path = tmp_path / "a.png"
    image_path.write_bytes(b"fake")
    calls: list[str] = []
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=[str(image_path)],
        sorted_image_files=[str(image_path)],
        current_index=0,
        _release_current_file_handles=lambda: None,
    )
    viewer._clear_display = lambda: calls.append("clear")
    viewer._remove_path_from_lists = lambda path: ImageViewer._remove_path_from_lists(viewer, path)

    ImageViewer.move_current_image_and_load_next(viewer, OK_FOLDER)

    assert (tmp_path / OK_FOLDER / "a.png").exists()
    assert viewer.image_files == []
    assert calls == ["clear"]


def test_move_current_image_and_load_next_reports_errors(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "a.png"
    status_bar = _StatusBar()
    viewer = SimpleNamespace(is_loading=False, image_files=[str(image_path)], current_index=0)
    viewer.statusBar = lambda: status_bar
    viewer._release_current_file_handles = lambda: None
    monkeypatch.setattr(navigation.shutil, "move", lambda *args: (_ for _ in ()).throw(OSError))

    ImageViewer.move_current_image_and_load_next(viewer, OK_FOLDER)

    assert status_bar.messages == [("エラー: ファイルの移動に失敗しました", 5000)]


def test_delete_current_image_and_load_next_clears_when_last_file(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "a.png"
    calls: list[str] = []
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=[str(image_path)],
        sorted_image_files=[str(image_path)],
        current_index=0,
        _release_current_file_handles=lambda: None,
    )
    viewer._clear_display = lambda: calls.append("clear")
    viewer._remove_path_from_lists = lambda path: ImageViewer._remove_path_from_lists(viewer, path)
    monkeypatch.setattr(navigation, "send2trash", lambda path: None)

    ImageViewer.delete_current_image_and_load_next(viewer)

    assert viewer.image_files == []
    assert calls == ["clear"]


def test_delete_current_image_and_load_next_reports_errors(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "a.png"
    status_bar = _StatusBar()
    viewer = SimpleNamespace(is_loading=False, image_files=[str(image_path)], current_index=0)
    viewer.statusBar = lambda: status_bar
    viewer._release_current_file_handles = lambda: None
    monkeypatch.setattr(navigation, "send2trash", lambda path: (_ for _ in ()).throw(OSError))

    ImageViewer.delete_current_image_and_load_next(viewer)

    assert status_bar.messages == [("エラー: ファイルの削除に失敗しました", 5000)]


def test_open_image_requests_selected_file(monkeypatch) -> None:
    loaded: list[str] = []
    viewer = SimpleNamespace(is_loading=False)
    viewer.load_image_from_path = loaded.append
    monkeypatch.setattr(
        main_window.QFileDialog,
        "getOpenFileName",
        lambda *args: ("selected.png", ""),
    )

    ImageViewer.open_image(viewer)

    assert loaded == ["selected.png"]


def test_open_image_ignores_loading_state() -> None:
    viewer = SimpleNamespace(is_loading=True)
    viewer.load_image_from_path = lambda path: (_ for _ in ()).throw(AssertionError)

    ImageViewer.open_image(viewer)


def test_redraw_image_dispatches_to_static_or_gif_renderer() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(original_pixmap=_Pixmap(), current_movie=None)
    viewer._redraw_static_image = lambda: calls.append("static")
    viewer._redraw_gif = lambda: calls.append("gif")

    ImageViewer.redraw_image(viewer)
    viewer.current_movie = _Movie()
    ImageViewer.redraw_image(viewer)

    assert calls == ["static", "gif"]


def test_redraw_image_ignores_null_pixmap() -> None:
    viewer = SimpleNamespace(original_pixmap=_Pixmap(is_null=True), current_movie=None)
    viewer._redraw_static_image = lambda: (_ for _ in ()).throw(AssertionError)

    ImageViewer.redraw_image(viewer)


def test_stop_movie_stops_and_clears_current_movie() -> None:
    movie = _Movie()
    label = _ImageLabel()
    label.setMovie(movie)
    viewer = SimpleNamespace(current_movie=movie, image_label=label)

    ImageViewer.stop_movie(viewer)

    assert movie.stopped is True
    assert viewer.current_movie is None
    assert label.movies == [movie, None]


def test_stop_movie_without_movie_leaves_label_alone() -> None:
    label = _ImageLabel()
    viewer = SimpleNamespace(current_movie=None, image_label=label)

    ImageViewer.stop_movie(viewer)

    assert label.movies == []


def _delete_sharing_error(path) -> int:
    """ファイルを削除共有で開けなければ、その Win32 エラーを返す。0 は掴まれていない。"""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    delete_access = 0x00010000
    share = 0x1 | 0x2 | 0x4  # READ | WRITE | DELETE
    handle = kernel32.CreateFileW(str(path), delete_access, share, None, 3, 0, None)
    error = ctypes.get_last_error()
    if error == 0:
        kernel32.CloseHandle(handle)
    return error


@pytest.mark.parametrize("suffix", [".gif", ".webp"])
def test_stop_movie_releases_qmovie_file_handle(qapp, tmp_path, suffix: str) -> None:
    import sys

    from PIL import Image
    from PyQt6.QtGui import QMovie
    from PyQt6.QtWidgets import QLabel

    path = tmp_path / f"anim{suffix}"
    frames = [Image.new("RGB", (8, 8), color) for color in ("red", "blue")]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)

    label = QLabel()
    movie = QMovie(str(path))
    assert movie.isValid()
    label.setMovie(movie)
    movie.start()
    qapp.processEvents()
    if sys.platform == "win32":
        assert _delete_sharing_error(path) == 32

    viewer = SimpleNamespace(current_movie=movie, image_label=label)
    ImageViewer.stop_movie(viewer)
    qapp.processEvents()

    assert viewer.current_movie is None
    assert label.movie() is None
    if sys.platform == "win32":
        # QMovie オブジェクトがまだ生きていても、ファイルは削除できる状態になっている
        assert _delete_sharing_error(path) == 0


def test_stop_movie_releases_apng_file_handle(qapp, tmp_path) -> None:
    import sys

    from PIL import Image
    from PyQt6.QtWidgets import QLabel

    from hiyoko_viewer.ui.apng_movie import ApngMovie

    path = tmp_path / "anim.png"
    frames = [Image.new("RGBA", (4, 4), color) for color in ((255, 0, 0, 255), (0, 255, 0, 255))]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=40, loop=0)
    movie = ApngMovie(str(path))
    assert movie.isValid()
    if sys.platform == "win32":
        assert _delete_sharing_error(path) == 32

    viewer = SimpleNamespace(current_movie=movie, image_label=QLabel())
    ImageViewer.stop_movie(viewer)

    assert viewer.current_movie is None
    assert movie._image is None
    if sys.platform == "win32":
        assert _delete_sharing_error(path) == 0


def test_update_status_bar_includes_shuffle_and_movie_state() -> None:
    status_bar = _StatusBar()
    frame_progress = _FrameProgress()
    frame_label = _FrameLabel()
    viewer = SimpleNamespace(
        original_pixmap=_Pixmap(),
        current_filesize=512 * 1024,
        fit_to_window=False,
        scale_factor=1.25,
        is_shuffled=True,
        current_movie=_Movie(QMovie.MovieState.Paused),
        frame_progress=frame_progress,
        frame_label=frame_label,
    )
    viewer.statusBar = lambda: status_bar

    ImageViewer.update_status_bar(viewer)

    assert status_bar.messages == [("🖼️ 200x100  |  💾 0.50MB  |   125.0%  |  🔀", None)]
    assert frame_progress.values == [(2, 3)]
    assert frame_label.texts == ["🎞️ [2/3] ⏸"]
    assert frame_label.visible is True


def test_handle_wheel_event_dispatches_zoom_or_scroll() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(is_loading=False)
    viewer._zoom_at_cursor = lambda event: calls.append("zoom")
    viewer._scroll_image = lambda event: calls.append("scroll")

    assert ImageViewer._handle_wheel_event(viewer, _WheelEvent(Qt.KeyboardModifier.ControlModifier))
    assert ImageViewer._handle_wheel_event(viewer, _WheelEvent(Qt.KeyboardModifier.NoModifier))
    viewer.is_loading = True
    assert ImageViewer._handle_wheel_event(viewer, _WheelEvent(Qt.KeyboardModifier.NoModifier))

    assert calls == ["zoom", "scroll"]


def test_mouse_press_starts_panning_or_toggles_gif(monkeypatch) -> None:
    cursors: list[object] = []
    monkeypatch.setattr(input_events, "QCursor", lambda shape: ("cursor", shape))
    viewer = SimpleNamespace(
        fit_to_window=False,
        space_key_pressed=True,
        is_panning=False,
        pan_last_mouse_pos=None,
    )
    viewer.setCursor = cursors.append
    viewer._toggle_gif_playback = lambda: False

    assert ImageViewer._handle_mouse_press_on_viewport(viewer, _MouseEvent())
    assert viewer.is_panning is True
    assert viewer.pan_last_mouse_pos.x() == 10
    assert cursors

    viewer.fit_to_window = True
    viewer.space_key_pressed = False
    viewer._toggle_gif_playback = lambda: True
    assert ImageViewer._handle_mouse_press_on_viewport(viewer, _MouseEvent())


def test_mouse_move_and_release_update_panning_state(monkeypatch) -> None:
    cursors: list[object] = []
    monkeypatch.setattr(input_events, "QCursor", lambda shape: ("cursor", shape))
    viewer = SimpleNamespace(
        is_panning=True,
        pan_last_mouse_pos=_Point(4, 8),
        scroll_area=_ScrollArea(),
        space_key_pressed=False,
    )
    viewer.setCursor = cursors.append

    assert ImageViewer._handle_mouse_move_on_viewport(viewer, _MouseEvent())
    assert viewer.scroll_area.horizontalScrollBar().value() == 94
    assert viewer.scroll_area.verticalScrollBar().value() == 188
    assert viewer.pan_last_mouse_pos.x() == 10

    assert ImageViewer._handle_mouse_release_on_viewport(viewer, _MouseEvent())
    assert viewer.is_panning is False
    assert cursors


def test_mouse_handlers_return_false_for_unhandled_events() -> None:
    viewer = SimpleNamespace(is_panning=False, fit_to_window=True, space_key_pressed=False)
    viewer._toggle_gif_playback = lambda: False

    assert (
        ImageViewer._handle_mouse_press_on_viewport(viewer, _MouseEvent(Qt.MouseButton.RightButton))
        is False
    )
    assert ImageViewer._handle_mouse_move_on_viewport(viewer, _MouseEvent()) is False
    assert ImageViewer._handle_mouse_release_on_viewport(viewer, _MouseEvent()) is False


def test_handle_key_press_on_scroll_area_blocks_keys_only_while_loading() -> None:
    loading = SimpleNamespace(is_loading=True)
    idle = SimpleNamespace(is_loading=False)

    assert ImageViewer._handle_key_press_on_scroll_area(loading, _KeyEvent(Qt.Key.Key_Right))
    assert ImageViewer._handle_key_press_on_scroll_area(idle, _KeyEvent(Qt.Key.Key_Right)) is False
    assert ImageViewer._handle_key_press_on_scroll_area(idle, _KeyEvent(Qt.Key.Key_Delete)) is False


def test_key_press_event_arms_pan_mode_for_space(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(input_events, "QCursor", lambda shape: ("cursor", shape))
    viewer = SimpleNamespace(is_loading=False, space_key_pressed=False)
    viewer.setCursor = lambda cursor: calls.append("cursor")

    ImageViewer.keyPressEvent(viewer, _KeyEvent(Qt.Key.Key_Space))

    assert viewer.space_key_pressed is True
    assert calls == ["cursor"]


def test_key_press_event_ignores_while_loading() -> None:
    event = _KeyEvent(Qt.Key.Key_F)
    viewer = SimpleNamespace(is_loading=True)

    ImageViewer.keyPressEvent(viewer, event)

    assert event.ignored is True


def test_key_release_event_clears_space_state() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(space_key_pressed=True, is_panning=True)
    viewer.unsetCursor = lambda: calls.append("unset")

    ImageViewer.keyReleaseEvent(viewer, _KeyEvent(Qt.Key.Key_Space))

    assert viewer.space_key_pressed is False
    assert viewer.is_panning is False
    assert calls == ["unset"]


def test_is_animated_webp_detects_animated_webp(monkeypatch) -> None:
    monkeypatch.setattr(
        rendering.Image, "open", lambda path: _ImageContext(is_animated=True, n_frames=2)
    )

    assert ImageViewer._is_animated_webp(SimpleNamespace(), "image.webp") is True


def test_is_animated_webp_returns_false_for_static_or_invalid_images(monkeypatch) -> None:
    assert ImageViewer._is_animated_webp(SimpleNamespace(), "image.png") is False

    monkeypatch.setattr(
        rendering.Image, "open", lambda path: _ImageContext(is_animated=True, n_frames=1)
    )
    assert ImageViewer._is_animated_webp(SimpleNamespace(), "image.webp") is False

    monkeypatch.setattr(rendering.Image, "open", lambda path: (_ for _ in ()).throw(OSError))
    assert ImageViewer._is_animated_webp(SimpleNamespace(), "broken.webp") is False


def test_update_image_display_sets_static_pixmap_and_title(monkeypatch) -> None:
    calls: list[str] = []
    titles: list[str] = []
    viewer = SimpleNamespace(
        image_files=["photo.png"],
        current_index=0,
        current_movie=None,
        image_label=_ImageLabel(),
        _load_generation=1,
    )
    viewer.stop_movie = lambda: calls.append("stop")
    viewer.redraw_image = lambda: calls.append("redraw")
    viewer.update_status_bar = lambda: calls.append("status")
    viewer.setWindowTitle = titles.append
    # worker は QImage を渡し、GUI スレッド側で QPixmap.fromImage で変換する
    monkeypatch.setattr(rendering, "QPixmap", _FakeQPixmap)

    image = _Pixmap()
    ImageViewer.update_image_display(viewer, 1, "photo.png", image)

    assert viewer.original_pixmap is image
    assert viewer.is_loading is False
    assert calls == ["stop", "redraw", "status"]
    assert titles == ["[1/1] photo.png"]


def test_update_image_display_uses_movie_for_gif(monkeypatch) -> None:
    movie = _Movie()
    titles: list[str] = []
    viewer = SimpleNamespace(
        image_files=["animation.gif"],
        current_index=0,
        current_movie=None,
        image_label=_ImageLabel(),
        _load_generation=1,
    )
    viewer.stop_movie = lambda: None
    viewer.on_gif_first_frame = lambda frame: None
    viewer.update_gif_frame_status = lambda frame: None
    viewer.setWindowTitle = titles.append
    monkeypatch.setattr(rendering, "QMovie", lambda path: movie)

    ImageViewer.update_image_display(viewer, 1, "animation.gif", _Pixmap())

    assert viewer.current_movie is movie
    assert viewer.image_label.movies == [movie]
    assert movie.started is True
    assert viewer.is_loading is False
    assert titles == ["[1/1] animation.gif"]


def test_update_image_display_uses_apng_movie_for_animated_png(monkeypatch) -> None:
    movie = _Movie()
    slots: list = []
    movie.frameChanged = SimpleNamespace(connect=slots.append)
    viewer = SimpleNamespace(
        image_files=["animation.png"],
        current_index=0,
        current_movie=None,
        image_label=_ImageLabel(),
        _load_generation=1,
    )
    viewer.stop_movie = lambda: None
    viewer.on_gif_first_frame = lambda frame: None
    viewer.update_gif_frame_status = lambda frame: None
    viewer._show_apng_frame = lambda frame: None
    viewer.setWindowTitle = lambda title: None
    monkeypatch.setattr(rendering, "is_animated_png", lambda path: True)
    monkeypatch.setattr(rendering, "ApngMovie", lambda path: movie)

    ImageViewer.update_image_display(viewer, 1, "animation.png", _Pixmap())

    assert viewer.current_movie is movie
    # QLabel.setMovie は QMovie 専用なので APNG では呼ばず、フレーム毎に pixmap を差し替える
    assert viewer.image_label.movies == []
    assert viewer._show_apng_frame in slots
    assert movie.started is True


def test_update_image_display_ignores_stale_path() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(
        image_files=["current.png"],
        current_index=0,
        current_movie=None,
        image_label=_ImageLabel(),
        _load_generation=1,
    )
    viewer.stop_movie = lambda: calls.append("stop")

    # 古いパスの結果が返ってきたら無視する
    ImageViewer.update_image_display(viewer, 1, "old.png", _Pixmap())

    assert calls == []


def test_update_image_display_ignores_empty_file_list() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(image_files=[], current_index=-1, _load_generation=1)
    viewer.stop_movie = lambda: calls.append("stop")

    ImageViewer.update_image_display(viewer, 1, "photo.png", _Pixmap())

    assert calls == []


def test_update_image_display_ignores_stale_generation() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(
        image_files=["photo.png"],
        current_index=0,
        current_movie=None,
        image_label=_ImageLabel(),
        _load_generation=2,
    )
    viewer.stop_movie = lambda: calls.append("stop")

    # 別ディレクトリを開き直した後（世代 2）に、古い世代 1 の結果が届いても無視する
    ImageViewer.update_image_display(viewer, 1, "photo.png", _Pixmap())

    assert calls == []


def test_on_gif_first_frame_sets_pixmap_and_disconnects() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(current_movie=_Movie())
    viewer.on_gif_first_frame = lambda frame: None
    viewer.redraw_image = lambda: calls.append("redraw")
    viewer.update_status_bar = lambda: calls.append("status")

    ImageViewer.on_gif_first_frame(viewer, 0)

    assert isinstance(viewer.original_pixmap, _Pixmap)
    assert calls == ["redraw", "status"]


def test_update_gif_frame_status_updates_when_movie_is_valid() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(current_movie=_Movie())
    viewer.update_status_bar = lambda: calls.append("status")

    ImageViewer.update_gif_frame_status(viewer, 0)

    assert calls == ["status"]


def test_toggle_fullscreen_enters_and_restores_window_state() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(_was_maximized_before_fullscreen=False)
    fullscreen = {"value": False}
    maximized = {"value": True}
    viewer.isFullScreen = lambda: fullscreen["value"]
    viewer.isMaximized = lambda: maximized["value"]
    viewer.showFullScreen = lambda: calls.append("fullscreen")
    viewer.showMaximized = lambda: calls.append("maximized")
    viewer.showNormal = lambda: calls.append("normal")

    ImageViewer._toggle_fullscreen(viewer)
    fullscreen["value"] = True
    ImageViewer._toggle_fullscreen(viewer)

    assert viewer._was_maximized_before_fullscreen is True
    assert calls == ["fullscreen", "maximized"]


def test_toggle_shuffle_mode_shuffles_and_loads(monkeypatch) -> None:
    calls: list[str] = []
    viewer = SimpleNamespace(
        image_files=["a.png", "b.png"],
        sorted_image_files=["a.png", "b.png"],
        current_index=1,
        is_shuffled=False,
    )
    viewer.load_image_by_index = lambda: calls.append("load")
    monkeypatch.setattr(navigation.random, "shuffle", lambda items: items.reverse())

    ImageViewer._toggle_shuffle_mode(viewer)

    assert viewer.is_shuffled is True
    assert viewer.image_files == ["b.png", "a.png"]
    assert viewer.current_index == 0
    assert calls == ["load"]


def test_redraw_static_image_fit_and_original_size_modes() -> None:
    label = _ImageLabel()
    scroll_area = _ScrollAreaWithViewport()
    viewer = SimpleNamespace(
        image_label=label,
        scroll_area=scroll_area,
        original_pixmap=_Pixmap(),
        svg_renderer=None,
        fit_to_window=True,
        scale_factor=1.5,
    )
    viewer._scaled_pixmap_for = lambda bounds: ImageViewer._scaled_pixmap_for(viewer, bounds)

    ImageViewer._redraw_static_image(viewer)
    viewer.fit_to_window = False
    ImageViewer._redraw_static_image(viewer)

    assert label.minimum_sizes == [(1, 1), (1, 1)]
    assert label.maximum_sizes == [(16777215, 16777215), (16777215, 16777215)]
    assert label.scaled_contents_values == [False, False]
    assert scroll_area.widget_resizable_values == [True, False]
    assert len(label.pixmaps) == 2
    assert label.pixmaps[-1].width() == 300
    assert label.pixmaps[-1].height() == 150
    assert label.adjusted is True


def test_render_svg_rasterizes_at_requested_size(qapp) -> None:
    from PyQt6.QtCore import QByteArray, QSize
    from PyQt6.QtSvg import QSvgRenderer

    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
        b'<rect width="100" height="50" fill="#3776ab"/></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg))
    assert renderer.isValid()
    viewer = SimpleNamespace(svg_renderer=renderer)

    # 固有サイズ(100x50)とは無関係に、要求したピクセルサイズで生成される＝ズームしても鮮明
    pixmap = ImageViewer._render_svg(viewer, QSize(800, 400))

    assert not pixmap.isNull()
    assert pixmap.width() == 800
    assert pixmap.height() == 400


def test_aspect_fit_size_keeps_aspect_ratio(qapp) -> None:
    from PyQt6.QtCore import QSize

    viewer = SimpleNamespace(original_pixmap=_Pixmap(width=100, height=50))

    # 横長(2:1)を 800x800 の枠に収めると 800x400 になる（高さで律速）
    fitted = ImageViewer._aspect_fit_size(viewer, QSize(800, 800))

    assert (fitted.width(), fitted.height()) == (800, 400)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_redraw_gif_fit_and_original_size_modes() -> None:
    label = _ImageLabel()
    scroll_area = _ScrollAreaWithViewport()
    movie = _Movie(QMovie.MovieState.NotRunning)
    viewer = SimpleNamespace(
        image_label=label,
        scroll_area=scroll_area,
        original_pixmap=_Pixmap(),
        fit_to_window=True,
        scale_factor=1.5,
        current_movie=movie,
    )

    ImageViewer._redraw_gif(viewer)
    viewer.fit_to_window = False
    ImageViewer._redraw_gif(viewer)

    assert label.scaled_contents_values == [True, True]
    assert scroll_area.widget_resizable_values == [False, False]
    assert len(label.fixed_sizes) == 2
    assert label.movies == [movie]
    assert movie.started is True

    paused = _Movie(QMovie.MovieState.Paused)
    viewer.current_movie = paused
    ImageViewer._redraw_gif(viewer)
    assert paused.started is False


def test_zoom_at_cursor_switches_from_fit_mode_and_scrolls() -> None:
    calls: list[str] = []
    scroll_area = _ScrollAreaWithViewport()
    viewer = SimpleNamespace(
        scale_factor=1.0,
        fit_to_window=True,
        original_pixmap=_Pixmap(),
        scroll_area=scroll_area,
    )
    viewer.redraw_image = lambda: calls.append("redraw")
    viewer.update_status_bar = lambda: calls.append("status")

    ImageViewer._zoom_at_cursor(viewer, _WheelEvent(Qt.KeyboardModifier.ControlModifier))

    assert viewer.fit_to_window is False
    assert viewer.scale_factor > 2.0
    assert scroll_area.horizontalScrollBar().value() > 100
    assert scroll_area.verticalScrollBar().value() > 200
    assert calls == ["redraw", "status"]


def test_zoom_at_cursor_returns_when_pixmap_width_is_zero() -> None:
    viewer = SimpleNamespace(
        scale_factor=1.0,
        fit_to_window=True,
        original_pixmap=_Pixmap(width=0, height=100),
        scroll_area=_ScrollAreaWithViewport(),
    )
    viewer.redraw_image = lambda: (_ for _ in ()).throw(AssertionError)

    ImageViewer._zoom_at_cursor(viewer, _WheelEvent(Qt.KeyboardModifier.ControlModifier))

    assert viewer.scale_factor == 1.0
    assert viewer.fit_to_window is True


def test_clear_display_resets_viewer_state(monkeypatch) -> None:
    status_bar = _StatusBar()
    label = _ImageLabel()
    titles: list[str] = []
    calls: list[str] = []
    frame_progress = _FrameProgress()
    viewer = SimpleNamespace(image_label=label, is_loading=True, frame_progress=frame_progress)
    viewer.stop_movie = lambda: calls.append("stop")
    viewer.statusBar = lambda: status_bar
    viewer.setWindowTitle = titles.append
    monkeypatch.setattr(rendering, "QPixmap", lambda: _Pixmap(is_null=True))

    ImageViewer._clear_display(viewer)

    assert calls == ["stop"]
    assert viewer.is_loading is False
    assert viewer.original_pixmap.isNull() is True
    assert label.texts == [constants.WELCOME_TEXT]
    assert label.styles == [constants.NOTICE_TEXT_STYLE]
    assert viewer.current_index == -1
    assert status_bar.messages == [("", None)]
    assert frame_progress.values == [(0, 0)]
    assert titles == [constants.DEFAULT_TITLE]


def test_coerce_recent_files_dedupes_and_caps() -> None:
    path = os.path.join("dir", "b.png")
    many = [f"{index}.png" for index in range(main_window.RECENT_FILE_LIMIT + 3)]

    assert main_window._coerce_recent_files([path, path, "a.gif", "", None]) == [
        os.path.normpath(path),
        os.path.normpath("a.gif"),
    ]
    assert main_window._coerce_recent_files("only.png") == [os.path.normpath("only.png")]
    assert main_window._coerce_recent_files(None) == []
    assert len(main_window._coerce_recent_files(many)) == main_window.RECENT_FILE_LIMIT
    assert main_window._coerce_recent_files(many)[0] == os.path.normpath(many[0])


def test_recent_file_label_numbers_escapes_and_disambiguates() -> None:
    path = os.path.join("dir", "a.png")
    assert main_window._recent_file_label(path, 0, [path]) == "&1 a.png"
    amp = os.path.join("dir", "a&b.png")
    assert main_window._recent_file_label(amp, 9, [amp]) == "&0 a&&b.png"
    one = os.path.join("one", "a.png")
    two = os.path.join("two", "a.png")
    assert main_window._recent_file_label(one, 1, [one, two]) == "&2 a.png (one)"
    older = os.path.join("2025", "output", "a.png")
    newer = os.path.join("2026", "output", "a.png")
    assert main_window._recent_file_label(older, 0, [older, newer]) == (
        f"&1 a.png (2025{os.sep}output)"
    )
    assert main_window._recent_file_label(newer, 1, [older, newer]) == (
        f"&2 a.png (2026{os.sep}output)"
    )


def test_load_settings_restores_recent_files(qapp, monkeypatch) -> None:
    from PyQt6.QtWidgets import QMenu

    _Settings.values = {
        "main_window/maximized": "false",
        "recent_files": [os.path.join("dir", "b.png"), os.path.join("dir", "b.png"), "a.gif"],
    }
    monkeypatch.setattr(main_window, "QSettings", _Settings)
    menu = QMenu()
    viewer = SimpleNamespace(recent_menu=menu)
    viewer.showMaximized = lambda: (_ for _ in ()).throw(AssertionError)
    viewer._rebuild_recent_menu = lambda: ImageViewer._rebuild_recent_menu(viewer)
    viewer._open_recent_file = lambda path: None
    viewer._clear_recent_files = lambda: None

    ImageViewer._load_settings(viewer)

    assert viewer._recent_files == [os.path.normpath(os.path.join("dir", "b.png")), "a.gif"]
    labels = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert labels[0].endswith("b.png")
    assert labels[1].endswith("a.gif")
    menu.deleteLater()


def test_load_settings_restores_maximized_window(monkeypatch) -> None:
    calls: list[str] = []
    _Settings.values = {"main_window/maximized": "true"}
    monkeypatch.setattr(main_window, "QSettings", _Settings)
    viewer = SimpleNamespace()
    viewer.showMaximized = lambda: calls.append("maximized")
    viewer.restoreGeometry = lambda geometry: calls.append("geometry")

    ImageViewer._load_settings(viewer)

    assert calls == ["maximized"]


def test_load_settings_restores_saved_geometry(monkeypatch) -> None:
    calls: list[bytes] = []
    _Settings.values = {"main_window/maximized": "false", "main_window/geometry": b"geometry"}
    monkeypatch.setattr(main_window, "QSettings", _Settings)
    viewer = SimpleNamespace()
    viewer.showMaximized = lambda: (_ for _ in ()).throw(AssertionError)
    viewer.restoreGeometry = lambda value: calls.append(value) or True
    viewer.geometry = lambda: QRect(0, 0, 800, 600)
    viewer._ensure_on_screen = lambda: calls.append("ensure")

    ImageViewer._load_settings(viewer)

    assert calls == [b"geometry", "ensure"]


def _screens_returning(*rects: QRect):
    return staticmethod(
        lambda: [SimpleNamespace(availableGeometry=lambda rect=rect: rect) for rect in rects]
    )


def _ensure_on_screen_with(monkeypatch, frame: QRect, *screens: QRect) -> list:
    monkeypatch.setattr(main_window.QApplication, "screens", _screens_returning(*screens))
    calls: list = []
    viewer = SimpleNamespace()
    viewer.frameGeometry = lambda: frame
    viewer.setGeometry = lambda *args: calls.append(args)
    ImageViewer._ensure_on_screen(viewer)
    return calls


def test_ensure_on_screen_keeps_geometry_when_visible(monkeypatch) -> None:
    calls = _ensure_on_screen_with(monkeypatch, QRect(100, 100, 800, 600), QRect(0, 0, 1920, 1080))

    assert calls == []


def test_ensure_on_screen_keeps_geometry_on_a_secondary_screen(monkeypatch) -> None:
    calls = _ensure_on_screen_with(
        monkeypatch,
        QRect(2000, 100, 800, 600),
        QRect(0, 0, 1920, 1080),
        QRect(1920, 0, 1920, 1080),
    )

    assert calls == []


def test_ensure_on_screen_falls_back_when_off_screen(monkeypatch) -> None:
    calls = _ensure_on_screen_with(
        monkeypatch, QRect(5000, 5000, 800, 600), QRect(0, 0, 1920, 1080)
    )

    assert calls == [(100, 100, 800, 600)]


def test_ensure_on_screen_falls_back_when_barely_overlapping(monkeypatch) -> None:
    # 右端に数 px 掛かっているだけの状態はユーザーが掴めないので画面外扱いにする
    calls = _ensure_on_screen_with(monkeypatch, QRect(1917, 100, 800, 600), QRect(0, 0, 1920, 1080))

    assert calls == [(100, 100, 800, 600)]


def test_save_settings_leaves_fullscreen_and_writes_geometry(monkeypatch) -> None:
    calls: list[str] = []
    _Settings.written = {}
    monkeypatch.setattr(main_window, "QSettings", _Settings)
    viewer = SimpleNamespace()
    viewer.isFullScreen = lambda: True
    viewer.showNormal = lambda: calls.append("normal")
    viewer.isMaximized = lambda: False
    viewer.saveGeometry = lambda: b"geometry"

    ImageViewer._save_settings(viewer)

    assert calls == ["normal"]
    assert _Settings.written == {
        "main_window/maximized": "false",
        "main_window/geometry": b"geometry",
    }


def test_save_settings_skips_geometry_when_maximized(monkeypatch) -> None:
    _Settings.written = {}
    monkeypatch.setattr(main_window, "QSettings", _Settings)
    viewer = SimpleNamespace()
    viewer.isFullScreen = lambda: False
    viewer.isMaximized = lambda: True
    viewer.saveGeometry = lambda: (_ for _ in ()).throw(AssertionError)

    ImageViewer._save_settings(viewer)

    assert _Settings.written == {"main_window/maximized": "true"}


def test_move_removes_path_from_sorted_image_files(tmp_path) -> None:
    image_path = tmp_path / "a.png"
    next_path = tmp_path / "b.png"
    image_path.write_bytes(b"fake")
    next_path.write_bytes(b"fake")
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=[str(image_path), str(next_path)],
        sorted_image_files=[str(image_path), str(next_path)],
        current_index=0,
        _release_current_file_handles=lambda: None,
    )
    viewer.load_image_by_index = lambda: None
    viewer._clear_display = lambda: None
    viewer._remove_path_from_lists = lambda path: ImageViewer._remove_path_from_lists(viewer, path)

    ImageViewer.move_current_image_and_load_next(viewer, "_ok")

    assert str(image_path) not in viewer.image_files
    assert str(image_path) not in viewer.sorted_image_files
    assert str(next_path) in viewer.sorted_image_files


def test_delete_removes_path_from_sorted_image_files(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "a.png"
    next_path = tmp_path / "b.png"
    viewer = SimpleNamespace(
        is_loading=False,
        image_files=[str(image_path), str(next_path)],
        sorted_image_files=[str(image_path), str(next_path)],
        current_index=0,
        _release_current_file_handles=lambda: None,
    )
    viewer.load_image_by_index = lambda: None
    viewer._clear_display = lambda: None
    viewer._remove_path_from_lists = lambda path: ImageViewer._remove_path_from_lists(viewer, path)
    monkeypatch.setattr(navigation, "send2trash", lambda path: None)

    ImageViewer.delete_current_image_and_load_next(viewer)

    assert str(image_path) not in viewer.image_files
    assert str(image_path) not in viewer.sorted_image_files
    assert str(next_path) in viewer.sorted_image_files


def test_close_event_hides_without_clearing_session() -> None:
    hidden = []
    released = []
    ignored = []

    class _Event:
        def ignore(self):
            ignored.append(True)

    viewer = SimpleNamespace(
        image_files=["photo.png"],
        current_index=0,
        current_movie=None,
        _resume_movie_on_show=False,
    )
    viewer.hide = lambda: hidden.append(True)
    viewer._release_current_file_handles = lambda: released.append(True)
    viewer._clear_display = lambda: (_ for _ in ()).throw(AssertionError("should not clear"))

    ImageViewer.closeEvent(viewer, _Event())

    assert hidden == [True]
    assert ignored == [True]
    assert released == [True]
    assert viewer._resume_movie_on_show is False
    assert viewer.image_files == ["photo.png"]
    assert viewer.current_index == 0


def test_close_event_marks_animation_to_resume() -> None:
    class _Event:
        def ignore(self):
            return None

    viewer = SimpleNamespace(
        image_files=["anim.gif"],
        current_index=0,
        current_movie=object(),
        _resume_movie_on_show=False,
    )
    viewer.hide = lambda: None
    viewer._release_current_file_handles = lambda: None

    ImageViewer.closeEvent(viewer, _Event())

    assert viewer._resume_movie_on_show is True


def test_show_window_resumes_movie_before_showing() -> None:
    calls: list[str] = []
    viewer = SimpleNamespace()
    viewer._resume_suspended_movie = lambda: calls.append("resume")
    viewer.setAttribute = lambda *_args: None
    viewer.show = lambda: calls.append("show")
    viewer.activateWindow = lambda: calls.append("activate")
    viewer.raise_ = lambda: calls.append("raise")

    ImageViewer.show_window(viewer)

    assert calls[0] == "resume"
    assert "show" in calls


def test_resume_suspended_movie_reopens_current_file() -> None:
    opened: list[str] = []
    viewer = SimpleNamespace(
        _resume_movie_on_show=True,
        is_loading=False,
        image_files=["anim.gif"],
        current_index=0,
        current_movie=None,
    )
    viewer._open_movie = lambda path: opened.append(path) or True
    viewer.redraw_image = lambda: opened.append("redraw")
    viewer.update_status_bar = lambda: opened.append("status")

    ImageViewer._resume_suspended_movie(viewer)

    assert opened == ["anim.gif", "redraw", "status"]
    assert viewer._resume_movie_on_show is False


def test_resume_reloads_existing_file_when_movie_will_not_open(qapp, tmp_path) -> None:
    path = tmp_path / "anim.gif"
    path.write_bytes(b"not-a-gif")
    loaded: list[str] = []
    viewer = SimpleNamespace(
        _resume_movie_on_show=True,
        is_loading=False,
        image_files=[str(path)],
        current_index=0,
        current_movie=None,
        _suspended_movie_frame=2,
        _suspended_movie_paused=True,
        original_pixmap=_Pixmap(),
        svg_renderer=object(),
        image_label=_ImageLabel(),
    )
    viewer._open_movie = lambda file_path: False
    viewer.stop_movie = lambda: None
    viewer.load_image_by_index = lambda: loaded.append(str(path))
    viewer._recover_failed_movie_resume = (
        lambda file_path: ImageViewer._recover_failed_movie_resume(viewer, file_path)
    )

    ImageViewer._resume_suspended_movie(viewer)

    assert loaded == [str(path)]
    assert viewer.original_pixmap.isNull()
    assert viewer._suspended_movie_frame is None


def test_update_image_display_defers_movie_while_hidden(monkeypatch) -> None:
    viewer = SimpleNamespace(
        image_files=["animation.gif"],
        current_index=0,
        current_movie=None,
        image_label=_ImageLabel(),
        _load_generation=1,
        _resume_movie_on_show=False,
    )
    viewer.isVisible = lambda: False
    viewer.stop_movie = lambda: None
    viewer.redraw_image = lambda: None
    viewer.update_status_bar = lambda: None
    viewer.setWindowTitle = lambda title: None
    monkeypatch.setattr(rendering, "QPixmap", _FakeQPixmap)
    monkeypatch.setattr(
        rendering,
        "QMovie",
        lambda path: (_ for _ in ()).throw(AssertionError("should not open")),
    )

    image = _Pixmap()
    ImageViewer.update_image_display(viewer, 1, "animation.gif", image)

    assert viewer._resume_movie_on_show is True
    assert viewer.current_movie is None
    assert viewer.original_pixmap is image


class _TrayViewer(SimpleNamespace):
    """setup_tray_icon のリトライ制御だけを検証するための最小スタブ"""

    setup_tray_icon = ImageViewer.setup_tray_icon


def _make_tray_viewer(results: list) -> _TrayViewer:
    viewer = _TrayViewer(_tray_setup_attempts=0, calls=0)

    def _setup_tray_icon() -> bool:
        outcome = results[viewer.calls]
        viewer.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    viewer._setup_tray_icon = _setup_tray_icon
    return viewer


def _patch_single_shot(monkeypatch) -> list:
    scheduled: list = []
    monkeypatch.setattr(
        main_window,
        "QTimer",
        SimpleNamespace(singleShot=lambda ms, fn: scheduled.append((ms, fn))),
    )
    return scheduled


def test_setup_tray_icon_does_not_retry_when_registered(monkeypatch) -> None:
    scheduled = _patch_single_shot(monkeypatch)
    viewer = _make_tray_viewer([True])

    viewer.setup_tray_icon()

    assert viewer.calls == 1
    assert scheduled == []


def test_setup_tray_icon_retries_until_registered(monkeypatch) -> None:
    scheduled = _patch_single_shot(monkeypatch)
    viewer = _make_tray_viewer([False, True])

    viewer.setup_tray_icon()
    assert len(scheduled) == 1
    assert scheduled[0][0] == main_window.TRAY_SETUP_RETRY_DELAY_MS

    scheduled[0][1]()  # リトライを実行
    assert viewer.calls == 2
    assert len(scheduled) == 1  # 成功したので追加スケジュールはしない


def test_setup_tray_icon_retries_after_exception_and_gives_up(monkeypatch) -> None:
    scheduled = _patch_single_shot(monkeypatch)
    attempts = main_window.TRAY_SETUP_MAX_ATTEMPTS
    viewer = _make_tray_viewer([RuntimeError("shell not ready")] * attempts)

    viewer.setup_tray_icon()
    while scheduled:
        _, retry = scheduled.pop()
        retry()

    # 例外は握りつぶし、上限回数で打ち切る（トレイ無しでも起動は続ける）
    assert viewer.calls == attempts
