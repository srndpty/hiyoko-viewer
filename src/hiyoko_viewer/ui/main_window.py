"""アプリケーションのメインウィンドウ。

描画 (:class:`RenderingMixin`)、ナビゲーション/ファイル操作
(:class:`NavigationMixin`)、入力イベント (:class:`InputEventMixin`) を
合成し、ウィンドウ固有の責務（UI 構築・トレイ・設定の保存復元・ダイアログ）を担う。
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSettings, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap
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

from ..config.constants import (
    DEFAULT_TITLE,
    NOTICE_TEXT_STYLE,
    SETTINGS_APP,
    SETTINGS_ORG,
    SUPPORTED_EXTENSIONS,
    WELCOME_TEXT,
)
from ..core.metadata import load_metadata_text
from ..core.resources import resource_path
from ..services.image_loader import ImageLoader
from .dialogs.metadata_dialog import MetadataDialog
from .mixins.input import InputEventMixin
from .mixins.navigation import NavigationMixin
from .mixins.rendering import RenderingMixin

if TYPE_CHECKING:
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMovie
    from PyQt6.QtSvg import QSvgRenderer

logger = logging.getLogger(__name__)


class ImageViewer(RenderingMixin, NavigationMixin, InputEventMixin, QMainWindow):
    request_load_image = pyqtSignal(int, str)  # (generation, path)
    request_load_list = pyqtSignal(int, str, str)  # (generation, directory, path)

    # --- インスタンス変数の型宣言 (Python 3.6+) ---
    fit_to_window: bool
    is_loading: bool
    is_shuffled: bool
    image_files: list[str]
    sorted_image_files: list[str]
    current_index: int
    original_pixmap: QPixmap
    svg_renderer: QSvgRenderer | None
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

        self._init_state_variables()
        self._setup_ui()
        self._setup_worker_thread()
        self._create_connections()
        self._load_settings()
        self._setup_tray_icon()

    # --------------------------------------------------------------------------
    # 初期化
    # --------------------------------------------------------------------------
    def _init_state_variables(self) -> None:
        """状態を管理するインスタンス変数を初期化する"""
        self.fit_to_window = True
        self.is_loading = False
        self._load_generation = 0
        self.is_shuffled = False
        self.image_files = []
        self.sorted_image_files = []
        self.current_index = -1
        self.original_pixmap = QPixmap()
        self.svg_renderer = None
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

    def _setup_worker_thread(self) -> None:
        """永続的なワーカースレッドを1つだけ作成し、起動する"""
        self.worker_thread = QThread()
        self.image_loader = ImageLoader()
        self.image_loader.moveToThread(self.worker_thread)
        # 別スレッドへ移した QObject は、そのスレッドの終了時にイベントループ上で破棄する
        self.worker_thread.finished.connect(self.image_loader.deleteLater)
        self.image_loader.image_loaded.connect(self.update_image_display)
        self.image_loader.list_loaded.connect(self.on_file_list_loaded)

        self.request_load_image.connect(self.image_loader.load_image)
        self.request_load_list.connect(self.image_loader.load_file_list)

        self.worker_thread.start()

    # --------------------------------------------------------------------------
    # システムトレイ
    # --------------------------------------------------------------------------
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

    def on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """トレイアイコンのクリックでウィンドウを復帰する"""
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

    # --------------------------------------------------------------------------
    # ウィンドウ操作 / ダイアログ
    # --------------------------------------------------------------------------
    def open_image(self) -> None:
        if self.is_loading:
            return
        filter_str = " ".join([f"*{ext}" for ext in SUPPORTED_EXTENSIONS])
        dialog_filter = f"対応画像ファイル ({filter_str});;すべてのファイル (*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "画像ファイルを開く", "", dialog_filter)
        self.load_image_from_path(file_path)

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

    def show_metadata_dialog(self):
        """現在の画像のメタデータを表示するダイアログを開く"""
        if not self.image_files or self.current_index < 0:
            return

        file_path = self.image_files[self.current_index]
        file_name = os.path.basename(file_path)
        final_text = load_metadata_text(file_path)

        # QMessageBox を使って情報を表示
        dialog = MetadataDialog(title=f"メタデータ: {file_name}", content=final_text, parent=self)
        dialog.exec()

    # --------------------------------------------------------------------------
    # 設定の保存と復元
    # --------------------------------------------------------------------------
    def _load_settings(self) -> None:
        """アプリケーションの設定を読み込み、ウィンドウの状態を復元する"""
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        # isMaximized() は show() の後でないと正しく機能しないため、フラグで代用
        if settings.value("main_window/maximized", "false", type=str).lower() == "true":
            self.showMaximized()
        else:
            # QSettings は保存した QByteArray を bytes ではなく QByteArray として
            # 返すことがあるため、型ではなく中身の有無で判定する
            geometry = settings.value("main_window/geometry")
            if geometry:
                self.restoreGeometry(geometry)

    def _save_settings(self) -> None:
        """現在のウィンドウの状態をアプリケーションの設定として保存する"""
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        # 全画面表示のまま終了した場合、通常表示としてジオメトリを保存
        if self.isFullScreen():
            self.showNormal()  # <<< 全画面を解除してから状態を取得

        settings.setValue("main_window/maximized", str(self.isMaximized()).lower())
        if not self.isMaximized():
            # saveGeometryはウィンドウの位置とサイズをまとめて保存する便利なメソッド
            settings.setValue("main_window/geometry", self.saveGeometry())
