from __future__ import annotations # <<< 型ヒントの記述を柔軟にするおまじない
import random
import sys
import os
import shutil
from typing import Optional, List # <<< 型ヒントのために Optional と List をインポート

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFileDialog, QSizePolicy, QScrollArea, QMenuBar, QStatusBar
)
from PyQt6.QtGui import (
    QPixmap, QKeyEvent, QCursor, QMovie, QIcon, QDragEnterEvent, QDropEvent, QMouseEvent, QWheelEvent, QCloseEvent
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QEvent, pyqtSlot, QPointF, QSettings
from send2trash import send2trash
from PIL import Image
import json
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox, QWidget
from PyQt6.QtGui import QFont, QFontDatabase 
import time
start_time = time.perf_counter() # <<< スクリプト開始直後に記録

SUPPORTED_EXTENSIONS = [
    '.bmp', '.cur', '.gif', '.icns', '.ico', '.jfif', '.jpeg', '.jpg', 
    '.pbm', '.pdf', '.pgm', '.png', '.ppm', '.svg', '.svgz', '.tga', 
    '.tif', '.tiff', '.wbmp', '.webp', '.xbm', '.xpm'
]
OK_FOLDER = "_ok"
NG_FOLDER = "_ng"
ZOOM_IN_FACTOR = 1.15
ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR
WELCOME_TEXT = "ファイル > 開く（Ctrl+O）またはドラッグアンドドロップで読み込む"
NOTICE_TEXT_STYLE = "font-size: 16pt; color: #555;"
DEFAULT_TITLE = "ひよこビューア"

def resource_path(relative_path: str) -> str: # <<< 型ヒントを追加
    """ 開発時とPyInstaller実行時の両方で、リソースへの正しいパスを取得する """
    try:
        base_path: str = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# main.py の先頭の import セクションに以下を追加
import re
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont

# ... (MetadataDialog クラスの前)

class JsonHighlighter(QSyntaxHighlighter):
    """JSONのシンタックスハイライトを行うためのクラス"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.highlighting_rules: list[tuple[re.Pattern, QTextCharFormat]] = []

        # キー ( "key": )
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#9CDCFE")) # 明るい青
        pattern = re.compile(r'"[^"]*"\s*:')
        self.highlighting_rules.append((pattern, key_format))

        # 文字列 ( "value" )
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178")) # オレンジ
        pattern = re.compile(r'"[^"]*"')
        self.highlighting_rules.append((pattern, string_format))

        # 数値 ( 123, 1.23 )
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#B5CEA8")) # 緑
        pattern = re.compile(r'\b-?\d+(\.\d+)?([eE][+-]?\d+)?\b')
        self.highlighting_rules.append((pattern, number_format))

        # 真偽値 ( true, false )
        boolean_format = QTextCharFormat()
        boolean_format.setForeground(QColor("#569CD6")) # 青
        boolean_format.setFontWeight(QFont.Weight.Bold)
        pattern = re.compile(r'\b(true|false)\b')
        self.highlighting_rules.append((pattern, boolean_format))
        
        # null
        null_format = QTextCharFormat()
        null_format.setForeground(QColor("#569CD6")) # 青
        null_format.setFontWeight(QFont.Weight.Bold)
        pattern = re.compile(r'\bnull\b')
        self.highlighting_rules.append((pattern, null_format))

    def highlightBlock(self, text: str) -> None:
        """テキストの各ブロック（行）にハイライトを適用する"""
        for pattern, format in self.highlighting_rules:
            # finditerを使って、行内の一致するすべての箇所を検索
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, format)

class MetadataDialog(QDialog):
    """メタデータを表示するためのカスタムダイアログ"""
    def __init__(self, title: str, content: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        self.setWindowTitle(title)
        self.content_text = content  # コピー機能のためにコンテンツを保持

        # メインレイアウト
        layout = QVBoxLayout(self)

        # スクロール可能なテキストエリア
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self.content_text)
        self.text_edit.setReadOnly(True)
        # JSONが見やすいように等幅フォントを設定
        # 1. 優先順位順にフォントの候補リストを作成
        font_candidates = ["Cascadia Code", "Consolas", "Courier New"]
        
        # 2. システムで利用可能な全フォントファミリーのリストを一度だけ取得する
        available_families = QFontDatabase.families()
        
        # 3. 候補リストをループし、利用可能なフォントファミリーリストに含まれているかチェック
        available_font = "Courier New" # 安全なデフォルト値
        for font_name in font_candidates:
            if font_name in available_families:
                available_font = font_name
                break # 最初に見つかったものを使う
        
        print(f"Using font: {available_font}") # デバッグ用にどのフォントが選ばれたか表示
        
        # 3. 見つかったフォントを適用
        font = QFont(available_font, 10)
        self.text_edit.setFont(font)
        # シンタックスハイライターを作成し、テキストドキュメントにアタッチする
        self.highlighter = JsonHighlighter(self.text_edit.document())
        # ボタン
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        copy_button = button_box.addButton("すべてコピー", QDialogButtonBox.ButtonRole.ActionRole)
        
        # UI要素をレイアウトに追加
        layout.addWidget(self.text_edit)
        layout.addWidget(button_box)

        # シグナルとスロットを接続
        button_box.accepted.connect(self.accept)  # OKボタンでダイアログを閉じる
        copy_button.clicked.connect(self.copy_to_clipboard)

        # ダイアログの初期サイズを設定
        self.resize(700, 600)

    def copy_to_clipboard(self) -> None:
        """テキストエリアの内容をクリップボードにコピーする"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.content_text)
        
        # 親ウィジェット（ImageViewer）のステータスバーにメッセージを表示
        if self.parent() and hasattr(self.parent(), 'statusBar'):
            self.parent().statusBar().showMessage("メタデータをクリップボードにコピーしました", 3000)

class ImageLoader(QObject):
    finished = pyqtSignal(QPixmap)

    def __init__(self) -> None: # <<< 型ヒントを追加
        super().__init__()

    @pyqtSlot(str)
    def load_image(self, file_path: str) -> None: # <<< 型ヒントを追加
        """ファイルパスを受け取って画像を読み込むスロット"""
        pixmap = QPixmap(file_path)
        self.finished.emit(pixmap)

class ImageViewer(QMainWindow):
    request_load_image = pyqtSignal(str)

    # --- インスタンス変数の型宣言 (Python 3.6+) ---
    fit_to_window: bool
    is_loading: bool
    is_shuffled: bool
    image_files: List[str]
    sorted_image_files: List[str]
    current_index: int
    original_pixmap: QPixmap
    current_movie: Optional[QMovie]
    current_filesize: int
    scale_factor: float
    space_key_pressed: bool
    is_panning: bool
    pan_last_mouse_pos: Optional[QPointF]
    worker_thread: QThread
    image_loader: ImageLoader
    image_label: QLabel
    scroll_area: QScrollArea
    
    def __init__(self) -> None:
        super().__init__()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "./settings") # <<< この行を追加
        self._init_state_variables()
        self._setup_ui()
        self._setup_worker_thread()
        self._create_connections()
        self._load_settings()

    def _setup_worker_thread(self) -> None:
        """永続的なワーカースレッドを1つだけ作成し、起動する"""
        self.worker_thread = QThread()
        self.image_loader = ImageLoader()
        self.image_loader.moveToThread(self.worker_thread)
        self.image_loader.finished.connect(self.update_image_display)
        self.request_load_image.connect(self.image_loader.load_image)
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
        self.setStatusBar(QStatusBar(self))

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
            elif event_type == QEvent.Type.MouseButtonDblClick: # ダブルクリックしたら画像読み込み
                # 何も読み込まれていない場合限定
                if not self.image_files:
                    self.open_image()
                    return True # イベントを消費
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
        self._save_settings() # <<< 設定保存を呼び出し
        self.worker_thread.quit()
        self.worker_thread.wait()
        super().closeEvent(event)

    # --------------------------------------------------------------------------
    # イベントヘルパー
    # --------------------------------------------------------------------------
    def _handle_wheel_event(self, event: QWheelEvent) -> bool:
        """ホイールイベントを処理する"""
        if self.is_loading: return True
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
            cursor_shape = Qt.CursorShape.OpenHandCursor if self.space_key_pressed else Qt.CursorShape.ArrowCursor
            self.setCursor(QCursor(cursor_shape))
            return True
        return False

    def _handle_key_press_on_scroll_area(self, event: QKeyEvent) -> bool:
        """スクロールエリアがフォーカス時のキー入力を処理する"""
        if self.is_loading: return True
        key = event.key()
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.KeypadModifier:
            if key == Qt.Key.Key_7:
                self.move_current_image_and_load_next(OK_FOLDER); return True
            elif key == Qt.Key.Key_9:
                self.move_current_image_and_load_next(NG_FOLDER); return True
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
            self.show_next_image(); return True
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self.show_prev_image(); return True
        elif key == Qt.Key.Key_Delete:
            self.delete_current_image_and_load_next(); return True
        elif key == Qt.Key.Key_Period:
            self._step_gif_frame(key); return True
        return False

    # --------------------------------------------------------------------------
    # コアロジック
    # --------------------------------------------------------------------------
    def load_image_from_path(self, file_path: str) -> None:
        """指定されたファイルパスから画像リストを生成し、読み込みを開始する"""
        if not file_path: return
        directory = os.path.dirname(file_path)
        sorted_list = sorted([
            os.path.normcase(os.path.join(directory, f)) 
            for f in os.listdir(directory) if f.lower().endswith(tuple(SUPPORTED_EXTENSIONS))
        ])
        self.sorted_image_files = sorted_list
        self.image_files = list(self.sorted_image_files)
        self.is_shuffled = False
        normalized_path = os.path.normcase(os.path.normpath(file_path))
        try:
            self.current_index = self.image_files.index(normalized_path)
            self.load_image_by_index()
        except ValueError:
            self.image_label.setText("画像の読み込みに失敗しました。")

    def load_image_by_index(self) -> None:
        """現在のインデックスに基づいて画像を非同期で読み込む"""
        if self.is_loading or not (0 <= self.current_index < len(self.image_files)): return
        self.fit_to_window = True
        self.scale_factor = 1.0
        self.is_loading = True
        file_path = self.image_files[self.current_index]
        try:
            self.current_filesize = os.path.getsize(file_path)
        except OSError:
            self.current_filesize = 0
        self.setWindowTitle(f"{self.windowTitle()} | 読み込み中...")
        # self.statusBar().showMessage("読み込み中...")
        self.request_load_image.emit(file_path)

    def show_next_image(self) -> None:
        if self.is_loading or not self.image_files: return
        self.current_index = (self.current_index + 1) % len(self.image_files)
        self.load_image_by_index()

    def show_prev_image(self) -> None:
        if self.is_loading or not self.image_files: return
        self.current_index = (self.current_index - 1 + len(self.image_files)) % len(self.image_files)
        self.load_image_by_index()

    def move_current_image_and_load_next(self, subfolder_name: str) -> None:
        if self.is_loading or not self.image_files: return
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
        except Exception as e:
            self.statusBar().showMessage(f"エラー: ファイルの移動に失敗しました", 5000)
            
    def delete_current_image_and_load_next(self) -> None:
        """現在の画像をごみ箱に移動し、次の画像を読み込む"""
        if self.is_loading or not self.image_files: return
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
        except Exception as e:
            self.statusBar().showMessage(f"エラー: ファイルの削除に失敗しました", 5000)

    # --------------------------------------------------------------------------
    # UI更新/スロット
    # --------------------------------------------------------------------------
    def open_image(self) -> None:
        if self.is_loading: return
        filter_str = " ".join([f"*{ext}" for ext in SUPPORTED_EXTENSIONS])
        dialog_filter = f"対応画像ファイル ({filter_str});;すべてのファイル (*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "画像ファイルを開く", "", dialog_filter)
        self.load_image_from_path(file_path)

    @pyqtSlot(QPixmap)
    def update_image_display(self, pixmap: QPixmap) -> None:
        self.stop_movie()
        file_path = self.image_files[self.current_index]
        if file_path.lower().endswith('.gif'):
            self.current_movie = QMovie(file_path)
            self.current_movie.frameChanged.connect(self.on_gif_first_frame)
            self.current_movie.frameChanged.connect(self.update_gif_frame_status)
            self.image_label.setMovie(self.current_movie)
            self.current_movie.start()
        else:
            if pixmap.isNull():
                self.image_label.setText("画像の読み込みに失敗しました")
                self.original_pixmap = QPixmap()
            else:
                self.original_pixmap = pixmap
            self.redraw_image()
            self.update_status_bar()
        self.setWindowTitle(f"[{self.current_index + 1}/{len(self.image_files)}] {os.path.basename(file_path)}")
        self.is_loading = False

    @pyqtSlot(int)
    def on_gif_first_frame(self, frame_number: int) -> None:
        if not self.current_movie: return
        first_frame_pixmap = self.current_movie.currentPixmap()
        if not first_frame_pixmap.isNull():
            self.original_pixmap = first_frame_pixmap
            try: self.current_movie.frameChanged.disconnect(self.on_gif_first_frame)
            except TypeError: pass
            self.redraw_image()
            self.update_status_bar()

    @pyqtSlot(int)
    def update_gif_frame_status(self, frame_number: int) -> None:
        if self.current_movie and self.current_movie.isValid():
            self.update_status_bar()

    def redraw_image(self) -> None:
        if self.original_pixmap.isNull(): return
        is_gif = self.current_movie and self.current_movie.isValid()
        if is_gif:
            self._redraw_gif()
        else:
            self._redraw_static_image()

    def update_status_bar(self) -> None:
        if self.original_pixmap.isNull():
            self.statusBar().clearMessage(); return
        parts: List[str] = []
        w, h = self.original_pixmap.width(), self.original_pixmap.height()
        fs_mb = f"{self.current_filesize / (1024*1024):.2f}MB"
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
            try: self.current_movie.frameChanged.disconnect()
            except TypeError: pass
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
            scaled_pixmap = self.original_pixmap.scaled(self.scroll_area.viewport().size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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
            scaled_pixmap = self.original_pixmap.scaled(self.scroll_area.viewport().size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.scroll_area.setWidgetResizable(False)
            scaled_pixmap = self.original_pixmap.scaled(int(self.original_pixmap.width() * self.scale_factor), int(self.original_pixmap.height() * self.scale_factor), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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
        if not self.image_files: return
        self.is_shuffled = not self.is_shuffled
        if self.is_shuffled:
            random.shuffle(self.image_files)
            self.current_index = 0
            self.load_image_by_index()
        else:
            current_path = self.image_files[self.current_index]
            self.image_files = list(self.sorted_image_files)
            self.current_index = self.image_files.index(current_path) if current_path in self.image_files else 0
            self.update_status_bar()

    def _zoom_at_cursor(self, event: QWheelEvent) -> None:
        old_scale_factor = self.scale_factor
        if self.fit_to_window:
            pixmap_size = self.original_pixmap.size()
            if pixmap_size.width() == 0: return
            vp_size = self.scroll_area.viewport().size()
            scale = min(vp_size.width() / pixmap_size.width(), vp_size.height() / pixmap_size.height())
            self.scale_factor = scale
            self.fit_to_window = False
        angle_delta = event.angleDelta().y()
        self.scale_factor *= ZOOM_IN_FACTOR if angle_delta > 0 else ZOOM_OUT_FACTOR
        self.redraw_image()
        mouse_pos = event.position()
        h_bar, v_bar = self.scroll_area.horizontalScrollBar(), self.scroll_area.verticalScrollBar()
        h_scroll = (h_bar.value() + mouse_pos.x()) * (self.scale_factor / old_scale_factor) - mouse_pos.x()
        v_scroll = (v_bar.value() + mouse_pos.y()) * (self.scale_factor / old_scale_factor) - mouse_pos.y()
        h_bar.setValue(int(h_scroll))
        v_bar.setValue(int(v_scroll))
        self.update_status_bar()
        
    def _scroll_image(self, event: QWheelEvent) -> None:
        scroll_amount = event.angleDelta().y() // 120 * 40
        if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.scroll_area.horizontalScrollBar().setValue(self.scroll_area.horizontalScrollBar().value() - scroll_amount)
        else:
            self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().value() - scroll_amount)
            
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
        if self.current_movie and self.current_movie.isValid() and self.current_movie.frameCount() > 0:
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
        self.update_status_bar()
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
            self.showNormal() # <<< 全画面を解除してから状態を取得

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
                if 'Comment' in image.info:
                    try:
                        # JSON文字列をPythonの辞書にパース
                        nai_data = json.loads(image.info['Comment'])
                        
                        metadata_parts.append("--- NovelAI パラメータ (JSON) ---\n")
                        # json.dumpsを使って、インデント付きの綺麗な文字列に変換
                        pretty_json = json.dumps(nai_data, indent=2, ensure_ascii=False)
                        metadata_parts.append(pretty_json)
                        metadata_parts.append("\n" + "-"*20 + "\n")

                    except json.JSONDecodeError:
                        # JSONとしてパースできない場合は、生のテキストとして表示
                        metadata_parts.append("--- NovelAI パラメータ (Comment) ---\n")
                        metadata_parts.append(image.info['Comment'])
                        metadata_parts.append("\n" + "-"*20 + "\n")

                # Stable Diffusion WebUI (A1111) は 'parameters' キーを使用
                elif 'parameters' in image.info:
                    metadata_parts.append("--- AI生成パラメータ (PNG) ---\n")
                    metadata_parts.append(image.info['parameters'])
                    metadata_parts.append("\n" + "-"*20 + "\n")

                # 念のため、'Description' も表示する (プレーンなプロンプトが入っている場合がある)
                if 'Description' in image.info and 'Comment' not in image.info:
                     metadata_parts.append("--- AI生成パラメータ (Description) ---\n")
                     metadata_parts.append(image.info['Description'])
                     metadata_parts.append("\n" + "-"*20 + "\n")
            
            # --- 2. Exif データをチェック ---
            exif_data = image.getexif()
            if exif_data:
                # PillowはExifタグをID(数値)で返すので、タグ名に変換する
                from PIL.ExifTags import TAGS
                
                exif_info = {
                    TAGS.get(key, key): value
                    for key, value in exif_data.items()
                }
                
                # AIプロンプトが含まれている可能性のある主要なExifタグ
                if 'UserComment' in exif_info:
                    # UserCommentは文字コード情報などが前に付いていることがあるのでデコードを試みる
                    try:
                        # Assuming the format might be like b'UNICODE\x00\x00\x00Prompt...'
                        decoded_comment = exif_info['UserComment'].decode('utf-8', errors='ignore')
                        # 'UNICODE' and null bytes might be at the start
                        if decoded_comment.startswith('UNICODE'):
                             decoded_comment = decoded_comment[8:].lstrip('\x00')
                        metadata_parts.append("--- AI生成パラメータ (UserComment) ---\n")
                        metadata_parts.append(decoded_comment)
                        metadata_parts.append("\n" + "-"*20 + "\n")

                    except (UnicodeDecodeError, AttributeError):
                        pass # デコードできない場合はスキップ

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
        dialog = MetadataDialog(
            title=f"メタデータ: {file_name}",
            content=final_text,
            parent=self
        )
        dialog.exec()

if __name__ == "__main__":
    main_start_time = time.perf_counter()
    app = QApplication(sys.argv)
    print(f"  - QApplication created: {time.perf_counter() - main_start_time:.4f} seconds")

    app_icon_path = resource_path("app_icon.ico")
    if os.path.exists(app_icon_path):
        app.setWindowIcon(QIcon(app_icon_path))
    viewer = ImageViewer()
    print(f"  - ImageViewer created: {time.perf_counter() - main_start_time:.4f} seconds")
    if len(sys.argv) > 1:
        initial_file_path = sys.argv[1]
        viewer.load_image_from_path(initial_file_path)
    viewer.show()
    print(f"  - viewer.show() called: {time.perf_counter() - main_start_time:.4f} seconds")     # 実際にウィンドウが表示されるのはイベントループが始まってから
    # 最初の描画イベントを捕捉するために QTimer.singleShot を使う
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, lambda: print(f"  - First paint event (approx): {time.perf_counter() - main_start_time:.4f} seconds"))
   
    sys.exit(app.exec())