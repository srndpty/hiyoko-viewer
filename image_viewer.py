from __future__ import annotations

import ctypes
import functools
import json
import locale
import os
import random
import re
import shutil
import sys

from PIL import Image
from PyQt6.QtCore import QEvent, QObject, QPointF, QSettings, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QCloseEvent,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QMovie,
    QPixmap,
    QWheelEvent,
)

# --- PyQt6 の import ---
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QScrollArea,
    QStatusBar,
    QSystemTrayIcon,
)

# --- 外部ライブラリの import ---
from send2trash import send2trash

# --- ローカルモジュールの import ---
from constants import (
    DEFAULT_TITLE,
    NG_FOLDER,
    NOTICE_TEXT_STYLE,
    OK_FOLDER,
    SUPPORTED_EXTENSIONS,
    WELCOME_TEXT,
    ZOOM_IN_FACTOR,
    ZOOM_OUT_FACTOR,
    resource_path,
)
from widgets import MetadataDialog
from worker import ImageLoader

# --- Windows 論理順ソート（Explorer の「名前」順）用ヘルパー ---

# natural_key はフォールバック用。数字を数値として扱う簡易ナチュラルソート。
_NATURAL_SPLIT_RE = re.compile(r"(\d+)")


def natural_key(path: str):
    name = os.path.basename(path)
    parts = _NATURAL_SPLIT_RE.split(name)
    return tuple(int(p) if p.isdigit() else p.casefold() for p in parts)


def _load_windows_logical_comparer():
    if not sys.platform.startswith("win"):
        return None

    try:
        shlwapi = ctypes.windll.Shlwapi
    except Exception:
        return None

    try:
        cmp_func = shlwapi.StrCmpLogicalW
        cmp_func.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        cmp_func.restype = ctypes.c_int
    except Exception:
        return None

    return cmp_func


_STRCMP_LOGICALW = _load_windows_logical_comparer()


def _create_windows_logical_key(comparer=_STRCMP_LOGICALW):
    """Windowsの論理順比較に基づくキーを生成する key 関数を返す。"""

    if comparer:

        def _cmp(a: str, b: str) -> int:
            # フォルダ内での並び順なので basename だけ比較する
            return comparer(os.path.basename(a), os.path.basename(b))

        # sorted(..., key=cmp_to_key(_cmp)) という形で使える「key」を返す
        return functools.cmp_to_key(_cmp)

    # ここから下は非 Windows や DLL が使えないときのフォールバック
    locale.setlocale(locale.LC_COLLATE, "")  # OS のロケールに合わせる
    locale_transform = locale.strxfrm

    def _fallback_key(path: str):
        name = os.path.basename(path)
        # まずロケール順、同値なら簡易ナチュラル順
        return (locale_transform(name.casefold()), natural_key(path))

    return _fallback_key


# 実際に sorted(..., key=windows_logical_key) で使うキー
windows_logical_key = _create_windows_logical_key()


class ImageViewer(QMainWindow):
    request_load_image = pyqtSignal(str)
    request_load_list = pyqtSignal(str, str)

    # --- インスタンス変数の型宣言 (Python 3.6+) ---
    fit_to_window: bool
    is_loading: bool
    is_shuffled: bool
    image_files: list[str]
    sorted_image_files: list[str]
    current_index: int
    original_pixmap: QPixmap
    current_movie: QMovie | None
    current_filesize: int
    scale_factor: float
    space_key_pressed: bool
    is_panning: bool
    pan_last_mouse_pos: QPointF | None
    worker_thread: QThread
    image_loader: ImageLoader
    image_label: QLabel
    scroll_area: QScrollArea

    def __init__(self) -> None:
        super().__init__()

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "./settings")
        self._init_state_variables()
        self._setup_ui()
        self._setup_worker_thread()
        self._create_connections()
        self._load_settings()
        self._setup_tray_icon()

    def _is_animated_webp(self, file_path: str) -> bool:
        """WebP がアニメーションかどうかを Pillow で判定する"""
        if not file_path.lower().endswith(".webp"):
            return False
        try:
            with Image.open(file_path) as im:
                # Pillow の WebP サポートが有効なら is_animated/n_frames が使える
                return bool(getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1)
        except Exception:
            # 壊れたファイルなどは安全側で False
            return False

    def _setup_tray_icon(self) -> None:
        """システムトレイアイコンとメニューを作成する"""
        self.tray_icon = QSystemTrayIcon(self)

        # resource_path を使ってアイコンを設定
        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))

        self.tray_icon.setToolTip(DEFAULT_TITLE)
        # --- 右クリックメニューの作成 ---
        tray_menu = QMenu()

        show_action = QAction("ひよこビューアを表示", self)
        show_action.triggered.connect(self.show_window)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        quit_action = QAction("完全に終了", self)
        # ここでは app.quit を直接呼ぶ
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)

        # --- 左クリックのアクションを接続 ---
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        self.tray_icon.show()

    # ★ 修正点 3: トレイアイコンがクリックされたときのスロット
    def on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """トレイアイコンのアクティベーションイベントを処理する"""
        # 左クリックまたはダブルクリックでウィンドウを表示
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def show_window(self) -> None:
        """ウィンドウを表示し、アクティブにする"""
        # 表示する直前に、フラッシュを防ぐための属性を設定する
        # WA_TranslucentBackground を使うと、Qtは自身の背景を描画せず、
        # 子ウィジェット（scroll_areaなど）が描画されるのを待つため、フラッシュが抑制される
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.show()
        self.activateWindow()
        self.raise_()  # 他のウィンドウの前面に表示する

    def _setup_worker_thread(self) -> None:
        """永続的なワーカースレッドを1つだけ作成し、起動する"""
        self.worker_thread = QThread()
        self.image_loader = ImageLoader()
        self.image_loader.moveToThread(self.worker_thread)
        # ★ 修正点 4: シグナル名を image_loaded に変更し、新しいシグナルを接続
        self.image_loader.image_loaded.connect(self.update_image_display)
        self.image_loader.list_loaded.connect(self.on_file_list_loaded)  # <<< 新しいスロットを接続

        self.request_load_image.connect(self.image_loader.load_image)
        self.request_load_list.connect(self.image_loader.load_file_list)  # <<< 新しいスロットを接続

        self.worker_thread.start()

    def _init_state_variables(self) -> None:
        """状態を管理するインスタンス変数を初期化する"""
        self.fit_to_window = True
        self.is_loading = False
        self.is_shuffled = False
        self.image_files = []
        self.sorted_image_files = []
        self.current_index = -1
        self.original_pixmap = QPixmap()
        self.current_movie = None
        self.current_filesize = 0
        self.scale_factor = 1.0
        self.space_key_pressed = False
        self.is_panning = False
        self.pan_last_mouse_pos = None
        self._was_maximized_before_fullscreen: bool = False

    def _setup_ui(self) -> None:
        """UIコンポーネントのセットアップを行う"""
        self.setWindowTitle(DEFAULT_TITLE)
        self.setGeometry(100, 100, 800, 600)
        self.setAcceptDrops(True)
        self.image_label = QLabel(WELCOME_TEXT)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(NOTICE_TEXT_STYLE)
        self.scroll_area = QScrollArea()
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setWidgetResizable(True)
        self.setCentralWidget(self.scroll_area)
        menu: QMenuBar = self.menuBar()
        file_menu = menu.addMenu("ファイル")
        self.open_action = file_menu.addAction("開く")
        self.open_action.setShortcut("Ctrl+O")
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #2D2D2D; /* 背景色をメインウィンドウと合わせる */
                color: #CCCCCC;           /* テキストの色 */
                border-top: 1px solid #444444; /* 上部に境界線を入れると見やすい（任意）*/
            }
            /* サイズグリップのスタイルも定義しておくと、より一貫性が出る */
            QStatusBar::item {
                border: none;
            }
        """)

    def _create_connections(self) -> None:
        """シグナルとスロット、イベントフィルターを接続する"""
        self.open_action.triggered.connect(self.open_image)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.installEventFilter(self)

    # --------------------------------------------------------------------------
    # イベントハンドラ
    # --------------------------------------------------------------------------
    def eventFilter(self, source: QObject, event: QEvent) -> bool:
        """イベントを横取りし、適切なハンドラにディスパッチする"""
        if source is self.scroll_area.viewport():
            event_type = event.type()
            if event_type == QEvent.Type.Wheel:
                # QWheelEvent にキャストして型安全性を高める
                self._handle_wheel_event(event)
                return True
            elif event_type == QEvent.Type.MouseButtonPress:
                return self._handle_mouse_press_on_viewport(event)
            elif event_type == QEvent.Type.MouseMove:
                return self._handle_mouse_move_on_viewport(event)
            elif event_type == QEvent.Type.MouseButtonRelease:
                return self._handle_mouse_release_on_viewport(event)
            elif event_type == QEvent.Type.MouseButtonDblClick:  # ダブルクリックしたら画像読み込み
                # 何も読み込まれていない場合限定
                if not self.image_files:
                    self.open_image()
                    return True  # イベントを消費
        if source is self.scroll_area and event.type() == QEvent.Type.KeyPress:
            if self._handle_key_press_on_scroll_area(event):
                return True

        return super().eventFilter(source, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """メインウィンドウが受け取るキーイベントを処理する"""
        if self.is_loading:
            event.ignore()
            return
        key = event.key()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_key_pressed = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        elif key == Qt.Key.Key_F11:
            self._toggle_fullscreen()
        elif key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_F:
            self._toggle_fit_mode()
        elif key == Qt.Key.Key_R:
            self._toggle_shuffle_mode()
        elif key == Qt.Key.Key_I:
            self.show_metadata_dialog()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not event.isAutoRepeat() and event.key() == Qt.Key.Key_Space:
            self.space_key_pressed = False
            self.is_panning = False
            self.unsetCursor()
        else:
            super().keyReleaseEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if urls := event.mimeData().urls():
            file_path = urls[0].toLocalFile()
            self.load_image_from_path(file_path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.fit_to_window:
            self.redraw_image()
        self.update_status_bar()

    def closeEvent(self, event: QCloseEvent) -> None:
        """ウィンドウが閉じられるときに呼ばれる"""
        # ★ 修正点 2: ウィンドウを非表示にする「前」に、表示をクリアする
        self._clear_display()
        event.ignore()
        self.hide()

    # --------------------------------------------------------------------------
    # イベントヘルパー
    # --------------------------------------------------------------------------
    def _handle_wheel_event(self, event: QWheelEvent) -> bool:
        """ホイールイベントを処理する"""
        if self.is_loading:
            return True
        modifiers = event.modifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            self._zoom_at_cursor(event)
        else:
            self._scroll_image(event)
        return True

    def _handle_mouse_press_on_viewport(self, event: QMouseEvent) -> bool:
        """ビューポート上でのマウスクリックを処理する。処理した場合のみ True を返す"""
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.fit_to_window and self.space_key_pressed:
                self.is_panning = True
                self.pan_last_mouse_pos = event.position()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                return True
            if self._toggle_gif_playback():
                return True
        return False

    def _handle_mouse_move_on_viewport(self, event: QMouseEvent) -> bool:
        """ビューポート上でのマウス移動を処理する"""
        if self.is_panning:
            delta = event.position() - self.pan_last_mouse_pos
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            h_bar.setValue(int(h_bar.value() - delta.x()))
            v_bar.setValue(int(v_bar.value() - delta.y()))
            self.pan_last_mouse_pos = event.position()
            return True
        return False

    def _handle_mouse_release_on_viewport(self, event: QMouseEvent) -> bool:
        """ビューポート上でのマウスボタン解放を処理する"""
        if self.is_panning and event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = False
            cursor_shape = (
                Qt.CursorShape.OpenHandCursor
                if self.space_key_pressed
                else Qt.CursorShape.ArrowCursor
            )
            self.setCursor(QCursor(cursor_shape))
            return True
        return False

    def _handle_key_press_on_scroll_area(self, event: QKeyEvent) -> bool:
        """スクロールエリアがフォーカス時のキー入力を処理する"""
        if self.is_loading:
            return True
        key = event.key()
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.KeypadModifier:
            if key == Qt.Key.Key_7:
                self.move_current_image_and_load_next(OK_FOLDER)
                return True
            elif key == Qt.Key.Key_9:
                self.move_current_image_and_load_next(NG_FOLDER)
                return True
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
            self.show_next_image()
            return True
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self.show_prev_image()
            return True
        elif key == Qt.Key.Key_Delete:
            self.delete_current_image_and_load_next()
            return True
        elif key == Qt.Key.Key_Period:
            self._step_gif_frame(key)
            return True
        return False

    # --------------------------------------------------------------------------
    # コアロジック
    # --------------------------------------------------------------------------

    def load_image_from_path(self, file_path: str) -> None:
        """ファイルリストの生成をワーカーに依頼する（非同期）"""
        if not file_path:
            return

        self._clear_display()  # <<< ★重要★ closeEventからこちらに移動
        # 重い処理はすべてワーカーに依頼するだけ
        directory = os.path.dirname(file_path)
        normalized_path = os.path.normcase(os.path.normpath(file_path))
        # UIはすぐに表示させ、裏でファイルリストの読み込みを依頼
        self.request_load_list.emit(directory, normalized_path)

    @pyqtSlot(list, int)
    def on_file_list_loaded(self, image_list: list, initial_index: int) -> None:
        """ワーカーからのファイルリスト読み込み完了通知を受け取る"""
        if not image_list:
            self.image_label.setText("画像の読み込みに失敗しました。")
            return

        # 念のため initial_index 範囲チェック
        if not (0 <= initial_index < len(image_list)):
            initial_index = 0

        # ワーカーが「最初に開いたファイル」として渡してきたパス
        selected_path = image_list[initial_index]

        # ★ ここで Windows 論理順（StrCmpLogicalW ベース）でソート
        self.sorted_image_files = sorted(image_list, key=windows_logical_key)
        self.image_files = list(self.sorted_image_files)
        self.is_shuffled = False

        # ソート後リスト中で selected_path がどこに来たかを探しなおす
        try:
            self.current_index = self.image_files.index(selected_path)
        except ValueError:
            # 万が一見つからなければ先頭にフォールバック
            self.current_index = 0

        # ファイルリストの準備ができたので、次に画像の読み込みを開始
        self.load_image_by_index()

    def load_image_by_index(self) -> None:
        """現在のインデックスに基づいて画像を非同期で読み込む"""
        if self.is_loading or not (0 <= self.current_index < len(self.image_files)):
            return
        self.fit_to_window = True
        self.scale_factor = 1.0
        self.is_loading = True
        file_path = self.image_files[self.current_index]
        try:
            self.current_filesize = os.path.getsize(file_path)
        except OSError:
            self.current_filesize = 0
        self.setWindowTitle(f"{self.windowTitle()} | 読み込み中...")
        self.statusBar().showMessage("読み込み中...")
        self.request_load_image.emit(file_path)

    def show_next_image(self) -> None:
        if self.is_loading or not self.image_files:
            return
        self.current_index = (self.current_index + 1) % len(self.image_files)
        self.load_image_by_index()

    def show_prev_image(self) -> None:
        if self.is_loading or not self.image_files:
            return
        self.current_index = (self.current_index - 1 + len(self.image_files)) % len(
            self.image_files
        )
        self.load_image_by_index()

    def move_current_image_and_load_next(self, subfolder_name: str) -> None:
        if self.is_loading or not self.image_files:
            return
        source_path = self.image_files[self.current_index]
        dest_folder = os.path.join(os.path.dirname(source_path), subfolder_name)
        os.makedirs(dest_folder, exist_ok=True)
        try:
            shutil.move(source_path, dest_folder)
            self.image_files.pop(self.current_index)
            if not self.image_files:
                self._clear_display()
            else:
                if self.current_index >= len(self.image_files):
                    self.current_index = 0
                self.load_image_by_index()
        except Exception:
            self.statusBar().showMessage("エラー: ファイルの移動に失敗しました", 5000)

    def delete_current_image_and_load_next(self) -> None:
        """現在の画像をごみ箱に移動し、次の画像を読み込む"""
        if self.is_loading or not self.image_files:
            return
        source_path = self.image_files[self.current_index]
        # ... (確認ダイアログのロジック) ...
        try:
            send2trash(source_path)
            self.image_files.pop(self.current_index)
            if not self.image_files:
                self._clear_display()
            else:
                if self.current_index >= len(self.image_files):
                    self.current_index = 0
                self.load_image_by_index()
        except Exception:
            self.statusBar().showMessage("エラー: ファイルの削除に失敗しました", 5000)

    # --------------------------------------------------------------------------
    # UI更新/スロット
    # --------------------------------------------------------------------------
    def open_image(self) -> None:
        if self.is_loading:
            return
        filter_str = " ".join([f"*{ext}" for ext in SUPPORTED_EXTENSIONS])
        dialog_filter = f"対応画像ファイル ({filter_str});;すべてのファイル (*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "画像ファイルを開く", "", dialog_filter)
        self.load_image_from_path(file_path)

    @pyqtSlot(QPixmap)
    def update_image_display(self, pixmap: QPixmap) -> None:
        self.stop_movie()
        file_path = self.image_files[self.current_index]
        ext = os.path.splitext(file_path)[1].lower()
        use_movie = False

        if ext == ".gif":
            use_movie = True
        elif ext == ".webp" and self._is_animated_webp(file_path):
            # アニメーション WebP だけ QMovie で扱う
            use_movie = True

        if use_movie:
            movie = QMovie(file_path)
            if movie.isValid():
                self.current_movie = movie
                self.current_movie.frameChanged.connect(self.on_gif_first_frame)
                self.current_movie.frameChanged.connect(self.update_gif_frame_status)
                self.image_label.setMovie(self.current_movie)
                self.current_movie.start()
            else:
                # 何らかの理由で QMovie が扱えなければ静止画フォールバック
                use_movie = False

        if not use_movie:
            if pixmap.isNull():
                self.image_label.setText("画像の読み込みに失敗しました")
                self.original_pixmap = QPixmap()
            else:
                self.original_pixmap = pixmap
            self.redraw_image()
            self.update_status_bar()

        self.setWindowTitle(
            f"[{self.current_index + 1}/{len(self.image_files)}] {os.path.basename(file_path)}"
        )
        self.is_loading = False

    @pyqtSlot(int)
    def on_gif_first_frame(self, frame_number: int) -> None:
        if not self.current_movie:
            return
        first_frame_pixmap = self.current_movie.currentPixmap()
        if not first_frame_pixmap.isNull():
            self.original_pixmap = first_frame_pixmap
            try:
                self.current_movie.frameChanged.disconnect(self.on_gif_first_frame)
            except TypeError:
                pass
            self.redraw_image()
            self.update_status_bar()

    @pyqtSlot(int)
    def update_gif_frame_status(self, frame_number: int) -> None:
        if self.current_movie and self.current_movie.isValid():
            self.update_status_bar()

    def redraw_image(self) -> None:
        if self.original_pixmap.isNull():
            return
        is_gif = self.current_movie and self.current_movie.isValid()
        if is_gif:
            self._redraw_gif()
        else:
            self._redraw_static_image()

    def update_status_bar(self) -> None:
        if self.original_pixmap.isNull():
            self.statusBar().clearMessage()
            return
        parts: list[str] = []
        w, h = self.original_pixmap.width(), self.original_pixmap.height()
        fs_mb = f"{self.current_filesize / (1024 * 1024):.2f}MB"
        parts.append(f"🖼️ {w}x{h}")
        parts.append(f"💾 {fs_mb}")
        if self.fit_to_window:
            vp_size = self.scroll_area.viewport().size()
            scale = min(vp_size.width() / w, vp_size.height() / h) if w > 0 and h > 0 else 0
            zoom_percent = scale * 100
            mode_icon = "↕️"
        else:
            zoom_percent = self.scale_factor * 100
            mode_icon = ""
        parts.append(f"{mode_icon} {zoom_percent:.1f}%")
        if self.is_shuffled:
            parts.append("🔀")
        if self.current_movie and self.current_movie.isValid():
            state = self.current_movie.state()
            state_icon = "►" if state == QMovie.MovieState.Running else "⏸"
            frame_info = f"🎞️ [{self.current_movie.currentFrameNumber() + 1}/{self.current_movie.frameCount()}]"
            parts.append(f"{frame_info} {state_icon}")
        status_text = "  |  ".join(parts)
        self.statusBar().showMessage(status_text)

    def stop_movie(self) -> None:
        if self.current_movie:
            try:
                self.current_movie.frameChanged.disconnect()
            except TypeError:
                pass
            self.current_movie.stop()
            self.current_movie = None
        self.image_label.setMovie(None)

    # --------------------------------------------------------------------------
    # 内部ヘルパー
    # --------------------------------------------------------------------------
    def _redraw_gif(self) -> None:
        self.image_label.setScaledContents(True)
        if self.fit_to_window:
            self.scroll_area.setWidgetResizable(False)
            scaled_pixmap = self.original_pixmap.scaled(
                self.scroll_area.viewport().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setFixedSize(scaled_pixmap.size())
        else:
            self.scroll_area.setWidgetResizable(False)
            scaled_size = self.original_pixmap.size() * self.scale_factor
            self.image_label.setFixedSize(scaled_size)
        if self.image_label.movie() is not self.current_movie:
            self.image_label.setMovie(self.current_movie)
        if self.current_movie and self.current_movie.state() != QMovie.MovieState.Running:
            self.current_movie.start()

    def _redraw_static_image(self) -> None:
        self.image_label.setMinimumSize(1, 1)
        self.image_label.setMaximumSize(16777215, 16777215)
        self.image_label.setScaledContents(False)
        if self.fit_to_window:
            self.scroll_area.setWidgetResizable(True)
            scaled_pixmap = self.original_pixmap.scaled(
                self.scroll_area.viewport().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.scroll_area.setWidgetResizable(False)
            scaled_pixmap = self.original_pixmap.scaled(
                int(self.original_pixmap.width() * self.scale_factor),
                int(self.original_pixmap.height() * self.scale_factor),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled_pixmap)
            self.image_label.adjustSize()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            # --- 全画面から復帰する場合 ---
            # 記憶しておいた状態に応じて復元する
            if self._was_maximized_before_fullscreen:
                self.showMaximized()
            else:
                self.showNormal()
        else:
            # --- 全画面に移行する場合 ---
            # 現在の最大化状態を記憶しておく
            self._was_maximized_before_fullscreen = self.isMaximized()
            self.showFullScreen()

    def _toggle_fit_mode(self) -> None:
        self.fit_to_window = not self.fit_to_window
        if not self.fit_to_window:
            self.scale_factor = 1.0
        self.redraw_image()
        self.update_status_bar()

    def _toggle_shuffle_mode(self) -> None:
        if not self.image_files:
            return
        self.is_shuffled = not self.is_shuffled
        if self.is_shuffled:
            random.shuffle(self.image_files)
            self.current_index = 0
            self.load_image_by_index()
        else:
            current_path = self.image_files[self.current_index]
            self.image_files = list(self.sorted_image_files)
            self.current_index = (
                self.image_files.index(current_path) if current_path in self.image_files else 0
            )
            self.update_status_bar()

    def _zoom_at_cursor(self, event: QWheelEvent) -> None:
        old_scale_factor = self.scale_factor
        if self.fit_to_window:
            pixmap_size = self.original_pixmap.size()
            if pixmap_size.width() == 0:
                return
            vp_size = self.scroll_area.viewport().size()
            scale = min(
                vp_size.width() / pixmap_size.width(), vp_size.height() / pixmap_size.height()
            )
            self.scale_factor = scale
            self.fit_to_window = False
        angle_delta = event.angleDelta().y()
        self.scale_factor *= ZOOM_IN_FACTOR if angle_delta > 0 else ZOOM_OUT_FACTOR
        self.redraw_image()
        mouse_pos = event.position()
        h_bar, v_bar = self.scroll_area.horizontalScrollBar(), self.scroll_area.verticalScrollBar()
        h_scroll = (h_bar.value() + mouse_pos.x()) * (
            self.scale_factor / old_scale_factor
        ) - mouse_pos.x()
        v_scroll = (v_bar.value() + mouse_pos.y()) * (
            self.scale_factor / old_scale_factor
        ) - mouse_pos.y()
        h_bar.setValue(int(h_scroll))
        v_bar.setValue(int(v_scroll))
        self.update_status_bar()

    def _scroll_image(self, event: QWheelEvent) -> None:
        scroll_amount = event.angleDelta().y() // 120 * 40
        if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.scroll_area.horizontalScrollBar().setValue(
                self.scroll_area.horizontalScrollBar().value() - scroll_amount
            )
        else:
            self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().value() - scroll_amount
            )

    def _toggle_gif_playback(self) -> bool:
        if self.current_movie and self.current_movie.isValid():
            state = self.current_movie.state()
            if state == QMovie.MovieState.Running:
                self.current_movie.setPaused(True)
            elif state == QMovie.MovieState.Paused:
                self.current_movie.setPaused(False)
            self.update_status_bar()
            return True
        return False

    def _step_gif_frame(self, key: int) -> None:
        if (
            self.current_movie
            and self.current_movie.isValid()
            and self.current_movie.frameCount() > 0
        ):
            current_frame = self.current_movie.currentFrameNumber()
            total_frames = self.current_movie.frameCount()
            new_frame = (current_frame + 1) % total_frames
            self.current_movie.jumpToFrame(new_frame)
            self.current_movie.setPaused(True)
            self.update_status_bar()

    def _clear_display(self) -> None:
        self.stop_movie()
        self.original_pixmap = QPixmap()
        self.image_label.setText(WELCOME_TEXT)
        self.image_label.setStyleSheet(NOTICE_TEXT_STYLE)
        self.current_index = -1
        self.statusBar().showMessage("")
        self.setWindowTitle(DEFAULT_TITLE)

    def _load_settings(self) -> None:
        """アプリケーションの設定を読み込み、ウィンドウの状態を復元する"""
        settings = QSettings("HiyokoSoft", "HiyokoViewer")

        # isMaximized() は show() の後でないと正しく機能しないため、フラグで代用
        if settings.value("main_window/maximized", "false", type=str).lower() == "true":
            self.showMaximized()
        else:
            geometry = settings.value("main_window/geometry")
            if isinstance(geometry, bytes):
                self.restoreGeometry(geometry)

    def _save_settings(self) -> None:
        """現在のウィンドウの状態をアプリケーションの設定として保存する"""
        settings = QSettings("HiyokoSoft", "HiyokoViewer")

        # 全画面表示のまま終了した場合、通常表示としてジオメトリを保存
        if self.isFullScreen():
            self.showNormal()  # <<< 全画面を解除してから状態を取得

        settings.setValue("main_window/maximized", str(self.isMaximized()).lower())
        if not self.isMaximized():
            # saveGeometryはウィンドウの位置とサイズをまとめて保存する便利なメソッド
            settings.setValue("main_window/geometry", self.saveGeometry())

    def show_metadata_dialog(self):
        """現在の画像のメタデータを表示するダイアログを開く"""
        if not self.image_files:
            return

        file_path = self.image_files[self.current_index]
        file_name = os.path.basename(file_path)

        try:
            image = Image.open(file_path)

            metadata_parts = []

            # --- 1. PNGの parameters (AIプロンプト) をチェック ---
            if image.info:
                # ★★★ ここからが NovelAI 対応の追加箇所 ★★★
                # NovelAI は 'Comment' キーにJSON形式で全パラメータを格納する
                if "Comment" in image.info:
                    try:
                        # JSON文字列をPythonの辞書にパース
                        nai_data = json.loads(image.info["Comment"])

                        metadata_parts.append("--- NovelAI パラメータ (JSON) ---\n")
                        # json.dumpsを使って、インデント付きの綺麗な文字列に変換
                        pretty_json = json.dumps(nai_data, indent=2, ensure_ascii=False)
                        metadata_parts.append(pretty_json)
                        metadata_parts.append("\n" + "-" * 20 + "\n")

                    except json.JSONDecodeError:
                        # JSONとしてパースできない場合は、生のテキストとして表示
                        metadata_parts.append("--- NovelAI パラメータ (Comment) ---\n")
                        metadata_parts.append(image.info["Comment"])
                        metadata_parts.append("\n" + "-" * 20 + "\n")

                # Stable Diffusion WebUI (A1111) は 'parameters' キーを使用
                elif "parameters" in image.info:
                    metadata_parts.append("--- AI生成パラメータ (PNG) ---\n")
                    metadata_parts.append(image.info["parameters"])
                    metadata_parts.append("\n" + "-" * 20 + "\n")

                # 念のため、'Description' も表示する (プレーンなプロンプトが入っている場合がある)
                if "Description" in image.info and "Comment" not in image.info:
                    metadata_parts.append("--- AI生成パラメータ (Description) ---\n")
                    metadata_parts.append(image.info["Description"])
                    metadata_parts.append("\n" + "-" * 20 + "\n")

            # --- 2. Exif データをチェック ---
            exif_data = image.getexif()
            if exif_data:
                # PillowはExifタグをID(数値)で返すので、タグ名に変換する
                from PIL.ExifTags import TAGS

                exif_info = {TAGS.get(key, key): value for key, value in exif_data.items()}

                # AIプロンプトが含まれている可能性のある主要なExifタグ
                if "UserComment" in exif_info:
                    # UserCommentは文字コード情報などが前に付いていることがあるのでデコードを試みる
                    try:
                        # Assuming the format might be like b'UNICODE\x00\x00\x00Prompt...'
                        decoded_comment = exif_info["UserComment"].decode("utf-8", errors="ignore")
                        # 'UNICODE' and null bytes might be at the start
                        if decoded_comment.startswith("UNICODE"):
                            decoded_comment = decoded_comment[8:].lstrip("\x00")
                        metadata_parts.append("--- AI生成パラメータ (UserComment) ---\n")
                        metadata_parts.append(decoded_comment)
                        metadata_parts.append("\n" + "-" * 20 + "\n")

                    except (UnicodeDecodeError, AttributeError):
                        pass  # デコードできない場合はスキップ

                metadata_parts.append("--- Exif 詳細 ---\n")
                for tag, value in exif_info.items():
                    # 値が長すぎる場合は短縮表示
                    value_str = str(value)
                    if len(value_str) > 100:
                        value_str = value_str[:100] + "..."
                    metadata_parts.append(f"{tag}: {value_str}")

            if not metadata_parts:
                final_text = "この画像には表示可能なメタデータが見つかりませんでした。"
            else:
                final_text = "\n".join(metadata_parts)

        except Exception as e:
            final_text = f"メタデータの読み込み中にエラーが発生しました:\n{e}"

        # QMessageBox を使って情報を表示
        dialog = MetadataDialog(title=f"メタデータ: {file_name}", content=final_text, parent=self)
        dialog.exec()
