"""アプリケーションのメインウィンドウ。

描画 (:class:`RenderingMixin`)、ナビゲーション/ファイル操作
(:class:`NavigationMixin`)、入力イベント (:class:`InputEventMixin`) を
合成し、ウィンドウ固有の責務（UI 構築・トレイ・設定の保存復元・ダイアログ）を担う。
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSettings, Qt, QThread, QTimer, pyqtSignal
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

    from .apng_movie import ApngMovie

logger = logging.getLogger(__name__)

# ウィンドウが「掴める」とみなす最小の可視サイズ（タイトルバー相当）
MIN_VISIBLE_WIDTH = 120
MIN_VISIBLE_HEIGHT = 30

# トレイ登録は Windows ログオン直後だと explorer.exe（シェル）が未準備で待たされる
# ことがある。ウィンドウ表示より後ろに回し、登録できなければ数回リトライする。
TRAY_SETUP_INITIAL_DELAY_MS = 1000
TRAY_SETUP_RETRY_DELAY_MS = 5000
TRAY_SETUP_MAX_ATTEMPTS = 5


class ImageViewer(RenderingMixin, NavigationMixin, InputEventMixin, QMainWindow):
    request_load_image = pyqtSignal(int, str)  # (generation, path)
    request_load_list = pyqtSignal(int, str, str)  # (generation, directory, path)
    request_warmup = pyqtSignal()  # 起動時のコーデック warmup 依頼

    # --- インスタンス変数の型宣言 (Python 3.6+) ---
    fit_to_window: bool
    is_loading: bool
    is_shuffled: bool
    image_files: list[str]
    sorted_image_files: list[str]
    current_index: int
    original_pixmap: QPixmap
    svg_renderer: QSvgRenderer | None
    current_movie: QMovie | ApngMovie | None
    current_filesize: int
    scale_factor: float
    space_key_pressed: bool
    is_panning: bool
    pan_last_mouse_pos: QPointF | None
    worker_thread: QThread
    image_loader: ImageLoader
    image_label: QLabel
    scroll_area: QScrollArea
    tray_icon: QSystemTrayIcon | None

    def __init__(self) -> None:
        super().__init__()

        # 起動フリーズの調査用。どの初期化まで進んだかをログだけで追えるようにする
        # （ログオン直後はワーカー起動・設定読み込み・トレイ登録で待たされうる）
        self._init_state_variables()
        self._setup_ui()
        logger.info("ui built")
        self._setup_worker_thread()
        logger.info("worker thread started")
        self._create_connections()
        self._load_settings()
        logger.info("settings loaded")
        # トレイ登録はここでは行わない。__init__ の中で待たされると show() まで到達
        # できず、「白いウィンドウのまま固まる」ことになるため、イベントループ開始後に
        # setup_tray_icon() を呼ぶ（呼び出しは app.main() 側）。

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
        self.tray_icon = None
        self._tray_setup_attempts = 0

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

        # スレッド起動後、最初のユーザー操作を待たずに画像コーデックを暖機する。
        # （worker スレッド上で走るので GUI/起動表示はブロックしない）
        self.request_warmup.connect(self.image_loader.warmup)
        self.request_warmup.emit()

    # --------------------------------------------------------------------------
    # システムトレイ
    # --------------------------------------------------------------------------
    def setup_tray_icon(self) -> None:
        """トレイアイコンを登録する（イベントループ開始後に呼ぶこと）。

        ``__init__`` から同期的に呼んではならない。ログオン直後はシェルの応答待ちで
        ここが返らず、``viewer.show()`` / ``app.exec()`` に到達できなくなる。
        登録に失敗した場合は :data:`TRAY_SETUP_RETRY_DELAY_MS` 後に再試行する。
        """
        self._tray_setup_attempts += 1
        attempt = self._tray_setup_attempts
        logger.info("tray setup: begin (attempt %s/%s)", attempt, TRAY_SETUP_MAX_ATTEMPTS)
        try:
            registered = self._setup_tray_icon()
        except Exception:
            # トレイはビューア本体の必須リソースではないので、失敗しても起動は続ける
            logger.exception("tray setup: raised (attempt %s)", attempt)
            registered = False

        if registered:
            logger.info("tray setup: done (attempt %s)", attempt)
            return
        if attempt >= TRAY_SETUP_MAX_ATTEMPTS:
            logger.warning("tray setup: giving up after %s attempts", attempt)
            return
        logger.info("tray setup: retrying in %s ms", TRAY_SETUP_RETRY_DELAY_MS)
        QTimer.singleShot(TRAY_SETUP_RETRY_DELAY_MS, self.setup_tray_icon)

    def _setup_tray_icon(self) -> bool:
        """トレイアイコンを作成して表示する。登録できたかを返す。

        どのネイティブ呼び出しで止まったのかをログだけで特定できるよう、Qt の各呼び
        出しの前後にログを残している（起動ハングの調査用の instrumentation）。
        """
        if self.tray_icon is None:
            self.tray_icon = self._create_tray_icon()

        # Qt はトレイが後から使えるようになれば（TaskbarCreated）自動で再登録するため、
        # ここでの可用性チェックは判断には使わず、記録だけに留める
        logger.info("tray setup: before isSystemTrayAvailable")
        available = QSystemTrayIcon.isSystemTrayAvailable()
        logger.info("tray setup: after isSystemTrayAvailable: %s", available)

        logger.info("tray setup: before show")
        self.tray_icon.show()
        visible = self.tray_icon.isVisible()
        logger.info("tray setup: after show (visible=%s)", visible)
        return visible

    def _create_tray_icon(self) -> QSystemTrayIcon:
        """システムトレイアイコンとメニューを作成する"""
        logger.info("tray setup: before QSystemTrayIcon ctor")
        tray_icon = QSystemTrayIcon(self)
        logger.info("tray setup: after QSystemTrayIcon ctor")

        # resource_path を使ってアイコンを設定
        icon_path = resource_path("app_icon.ico")
        logger.info("tray setup: icon path resolved: %s", icon_path)
        if os.path.exists(icon_path):
            logger.info("tray setup: before QIcon")
            icon = QIcon(icon_path)
            logger.info("tray setup: after QIcon")

            logger.info("tray setup: before setIcon")
            tray_icon.setIcon(icon)
            logger.info("tray setup: after setIcon")

        logger.info("tray setup: before setToolTip")
        tray_icon.setToolTip(DEFAULT_TITLE)
        logger.info("tray setup: after setToolTip")

        # --- 右クリックメニューの作成 ---
        logger.info("tray setup: before QMenu")
        tray_menu = QMenu()
        logger.info("tray setup: after QMenu")

        show_action = QAction("ひよこビューアを表示", self)
        show_action.triggered.connect(self.show_window)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        quit_action = QAction("完全に終了", self)
        # ここでは app.quit を直接呼ぶ
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)
        logger.info("tray setup: menu built")

        # メニューは tray_icon に所有されないため、参照を保持しないと破棄される
        self._tray_menu = tray_menu

        logger.info("tray setup: before setContextMenu")
        tray_icon.setContextMenu(tray_menu)
        logger.info("tray setup: after setContextMenu")

        # --- 左クリックのアクションを接続 ---
        logger.info("tray setup: before activated.connect")
        tray_icon.activated.connect(self.on_tray_icon_activated)
        logger.info("tray setup: after activated.connect")

        return tray_icon

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
                restored = self.restoreGeometry(geometry)
                logger.info("restoreGeometry returned %s -> %s", restored, self.geometry())
                self._ensure_on_screen()

    def _ensure_on_screen(self) -> None:
        """復元したジオメトリが実質的に画面外なら、既定位置に戻す（多重防御）。

        ``restoreGeometry()`` 自体が利用可能な画面内へ補正する仕様なので通常は不要。
        ただしトレイ常駐アプリでウィンドウが掴めない状態になると「起動したのに何も
        出ない」となり復帰手段に乏しいため、補正をすり抜けた異常なジオメトリを
        最後に弾いておく。
        """
        frame = self.frameGeometry()
        for screen in QApplication.screens():
            visible = screen.availableGeometry().intersected(frame)
            # 数 px だけ掛かっている状態は掴めないので「見えている」とみなさない
            if visible.width() >= MIN_VISIBLE_WIDTH and visible.height() >= MIN_VISIBLE_HEIGHT:
                return
        logger.warning("restored geometry %s is not usable; falling back to default", frame)
        self.setGeometry(100, 100, 800, 600)

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
