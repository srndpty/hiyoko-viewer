import random
import sys
import os
import shutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFileDialog, QSizePolicy, QScrollArea
)
from PyQt6.QtGui import QPixmap, QKeyEvent, QCursor, QMovie, QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QEvent
from send2trash import send2trash

# <<< REFACTOR: Step 1 - 定数の分離 >>>
# ハードコーディングされた値をファイルスコープの定数として定義
SUPPORTED_EXTENSIONS = [
    '.bmp', '.cur', '.gif', '.icns', '.ico', '.jfif', '.jpeg', '.jpg', 
    '.pbm', '.pdf', '.pgm', '.png', '.ppm', '.svg', '.svgz', '.tga', 
    '.tif', '.tiff', '.wbmp', '.webp', '.xbm', '.xpm'
]
OK_FOLDER = "_ok"
NG_FOLDER = "_ng"
ZOOM_IN_FACTOR = 1.15
ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR

# ... (import shutil の後など)
def resource_path(relative_path):
    """ 開発時とPyInstaller実行時の両方で、リソースへの正しいパスを取得する """
    try:
        # PyInstallerは、一時フォルダのパスを _MEIPASS に格納する
        base_path = sys._MEIPASS
    except Exception:
        # PyInstaller以外で実行されている場合（開発時）
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class ImageLoader(QObject):
    finished = pyqtSignal(QPixmap)
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
    def run(self):
        pixmap = QPixmap(self.file_path)
        self.finished.emit(pixmap)


class ImageViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        # <<< REFACTOR: Step 2 - __init__ の分割 >>>
        self._init_state_variables()
        self._setup_ui()
        self._create_connections()

    # --------------------------------------------------------------------------
    # <<< REFACTOR: Step 4 - メソッドのグルーピング (初期化) >>>
    # --------------------------------------------------------------------------
    def _init_state_variables(self):
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

    def _setup_ui(self):
        """UIコンポーネントのセットアップを行う"""
        self.setWindowTitle("画像ビューア")
        self.setGeometry(100, 100, 800, 600)
        self.setAcceptDrops(True)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.scroll_area = QScrollArea()
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setWidgetResizable(True)
        self.setCentralWidget(self.scroll_area)

        menu = self.menuBar()
        file_menu = menu.addMenu("ファイル")
        self.open_action = file_menu.addAction("開く")
        self.open_action.setShortcut("Ctrl+O")

    def _create_connections(self):
        """シグナルとスロット、イベントフィルターを接続する"""
        self.open_action.triggered.connect(self.open_image)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.installEventFilter(self)

    # --------------------------------------------------------------------------
    # <<< REFACTOR: Step 4 - メソッドのグルーピング (イベントハンドラ) >>>
    # --------------------------------------------------------------------------
    def eventFilter(self, source, event):
        """イベントを横取りし、適切なハンドラにディスパッチする"""
        if source is self.scroll_area.viewport():
            event_type = event.type()
            # ★ 修正点 1: すべてのマウスイベントをここで処理するように拡張
            if event_type == QEvent.Type.Wheel:
                self._handle_wheel_event(event)
                return True
            elif event_type == QEvent.Type.MouseButtonPress:
                # ヘルパーが True を返した場合のみイベントを消費する
                return self._handle_mouse_press_on_viewport(event)
            elif event_type == QEvent.Type.MouseMove:
                return self._handle_mouse_move_on_viewport(event)
            elif event_type == QEvent.Type.MouseButtonRelease:
                return self._handle_mouse_release_on_viewport(event)
        
        if source is self.scroll_area and event.type() == QEvent.Type.KeyPress:
            if self._handle_key_press_on_scroll_area(event):
                return True

        return super().eventFilter(source, event)

    def keyPressEvent(self, event):
        """メインウィンドウが受け取るキーイベントを処理する"""
        print(f"Key Pressed: {event.key()}")
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
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat() and event.key() == Qt.Key.Key_Space:
            self.space_key_pressed = False
            self.is_panning = False
            self.unsetCursor()
        else:
            super().keyReleaseEvent(event)

    def _handle_mouse_press_on_viewport(self, event):
        """ビューポート上でのマウスクリックを処理する。処理した場合のみ True を返す"""
        if event.button() == Qt.MouseButton.LeftButton:
            # ★ 修正点 2: パンニング開始のロジックをここに移管
            if not self.fit_to_window and self.space_key_pressed:
                self.is_panning = True
                self.pan_last_mouse_pos = event.position() # .pos() ではなく .position()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                return True # イベントを処理した
            
            # GIF再生トグルのロジック
            if self._toggle_gif_playback():
                return True # イベントを処理した
        
        return False # イベントを処理しなかった

    # ★ 修正点 3: 新しいマウスイベントヘルパーを追加
    def _handle_mouse_move_on_viewport(self, event):
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

    def _handle_mouse_release_on_viewport(self, event):
        """ビューポート上でのマウスボタン解放を処理する"""
        if self.is_panning and event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = False
            cursor_shape = Qt.CursorShape.OpenHandCursor if self.space_key_pressed else Qt.CursorShape.ArrowCursor
            self.setCursor(QCursor(cursor_shape))
            return True
        return False
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if urls := event.mimeData().urls():
            file_path = urls[0].toLocalFile()
            self.load_image_from_path(file_path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_to_window:
            self.redraw_image()
        self.update_status_bar()

    # --------------------------------------------------------------------------
    # <<< REFACTOR: Step 4 - メソッドのグルーピング (イベントヘルパー) >>>
    # --------------------------------------------------------------------------
    def _handle_wheel_event(self, event):
        """ホイールイベントを処理する"""
        if self.is_loading: return True
        
        modifiers = event.modifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            self._zoom_at_cursor(event)
        else:
            self._scroll_image(event)
        return True

    def _handle_key_press_on_scroll_area(self, event):
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
    # <<< REFACTOR: Step 4 - メソッドのグルーピング (コアロジック) >>>
    # --------------------------------------------------------------------------
    def load_image_from_path(self, file_path):
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

    def load_image_by_index(self):
        """現在のインデックスに基づいて画像を非同期で読み込む"""
        if self.is_loading or not (0 <= self.current_index < len(self.image_files)): return
        
        self.stop_movie()
        self.fit_to_window = True
        self.scale_factor = 1.0
        self.is_loading = True

        file_path = self.image_files[self.current_index]
        try:
            self.current_filesize = os.path.getsize(file_path)
        except OSError:
            self.current_filesize = 0
        
        self.setWindowTitle(f"読み込み中... {os.path.basename(file_path)}")
        self.image_label.setText("読み込み中...")

        self.thread = QThread()
        self.worker = ImageLoader(file_path)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.finished.connect(self.update_image_display)
        self.thread.start()

    def show_next_image(self):
        if self.is_loading or not self.image_files: return
        self.current_index = (self.current_index + 1) % len(self.image_files)
        self.load_image_by_index()

    def show_prev_image(self):
        if self.is_loading or not self.image_files: return
        self.current_index = (self.current_index - 1 + len(self.image_files)) % len(self.image_files)
        self.load_image_by_index()

    def move_current_image_and_load_next(self, subfolder_name):
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

    # --------------------------------------------------------------------------
    # <<< REFACTOR: Step 4 - メソッドのグルーピング (UI更新/スロット) >>>
    # --------------------------------------------------------------------------
    def open_image(self):
        if self.is_loading: return
        filter_str = " ".join([f"*{ext}" for ext in SUPPORTED_EXTENSIONS])
        dialog_filter = f"対応画像ファイル ({filter_str});;すべてのファイル (*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "画像ファイルを開く", "", dialog_filter)
        self.load_image_from_path(file_path)

    def update_image_display(self, pixmap):
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

    def on_gif_first_frame(self, frame_number):
        if not self.current_movie: return
        first_frame_pixmap = self.current_movie.currentPixmap()
        if not first_frame_pixmap.isNull():
            self.original_pixmap = first_frame_pixmap
            try:
                self.current_movie.frameChanged.disconnect(self.on_gif_first_frame)
            except TypeError: pass
            self.redraw_image()
            self.update_status_bar()

    def update_gif_frame_status(self, frame_number):
        if self.current_movie and self.current_movie.isValid():
            self.update_status_bar()

    def redraw_image(self):
        if self.original_pixmap.isNull(): return
        
        is_gif = self.current_movie and self.current_movie.isValid()
        if is_gif:
            self._redraw_gif()
        else:
            self._redraw_static_image()

    def update_status_bar(self):
        if self.original_pixmap.isNull():
            self.statusBar().clearMessage()
            return

        parts = [] # ステータスバーの各パーツを格納するリスト

        # 1. 画像の基本情報
        w, h = self.original_pixmap.width(), self.original_pixmap.height()
        fs_mb = f"{self.current_filesize / (1024*1024):.2f}MB"
        parts.append(f"🖼️ {w}x{h}")
        parts.append(f"💾 {fs_mb}")

        # 2. ズームとモードの情報
        if self.fit_to_window:
            vp_size = self.scroll_area.viewport().size()
            scale = min(vp_size.width() / w, vp_size.height() / h) if w > 0 and h > 0 else 0
            zoom_percent = scale * 100
            mode_icon = "↕️"
        else:
            zoom_percent = self.scale_factor * 100
            mode_icon = ""
        
        parts.append(f"{mode_icon} {zoom_percent:.1f}%")

        # 3. ランダムモードの情報
        if self.is_shuffled:
            parts.append("🔀")

        # 4. GIFの再生状態とフレーム情報
        if self.current_movie and self.current_movie.isValid():
            state = self.current_movie.state()
            state_icon = "►" if state == QMovie.MovieState.Running else "⏸"
            
            frame_info = f"🎞️ {self.current_movie.currentFrameNumber() + 1}/{self.current_movie.frameCount()}"
            parts.append(f"{state_icon} {frame_info}")

        # すべてのパーツをセパレータで結合して表示
        status_text = "  |  ".join(parts)
        self.statusBar().showMessage(status_text)

    def stop_movie(self):
        if self.current_movie:
            try: self.current_movie.frameChanged.disconnect()
            except TypeError: pass
            self.current_movie.stop()
            self.current_movie = None
        self.image_label.setMovie(None)

    # --------------------------------------------------------------------------
    # <<< REFACTOR: Step 4 - メソッドのグルーピング (内部ヘルパー) >>>
    # --------------------------------------------------------------------------
    def _redraw_gif(self):
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
        if self.current_movie.state() != QMovie.MovieState.Running:
            self.current_movie.start()

    def _redraw_static_image(self):
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

    def _toggle_fullscreen(self):
        print("Toggling fullscreen")
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
    
    def _toggle_fit_mode(self):
        print("Toggling fit mode")
        if self.fit_to_window:
            self.fit_to_window = False
            self.scale_factor = 1.0
        else:
            self.fit_to_window = True
        self.redraw_image()
        self.update_status_bar()

    def _toggle_shuffle_mode(self):
        print("Toggling shuffle mode")
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

    def _zoom_at_cursor(self, event):
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
        
    def _scroll_image(self, event):
        scroll_amount = event.angleDelta().y() // 120 * 40
        if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.scroll_area.horizontalScrollBar().setValue(self.scroll_area.horizontalScrollBar().value() - scroll_amount)
        else:
            self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().value() - scroll_amount)
            
    def _toggle_gif_playback(self):
        if self.current_movie and self.current_movie.isValid():
            state = self.current_movie.state()
            if state == QMovie.MovieState.Running:
                self.current_movie.setPaused(True)
            elif state == QMovie.MovieState.Paused:
                self.current_movie.setPaused(False)
            self.update_status_bar()
            return True
        return False

    def _step_gif_frame(self, key):
        if self.current_movie and self.current_movie.isValid() and self.current_movie.frameCount() > 0:
            current_frame = self.current_movie.currentFrameNumber()
            total_frames = self.current_movie.frameCount()
            new_frame = (current_frame + 1) % total_frames
            
            self.current_movie.jumpToFrame(new_frame)
            self.current_movie.setPaused(True)
            self.update_status_bar()

    def _clear_display(self):
        self.stop_movie()
        self.original_pixmap = QPixmap()
        self.image_label.clear()
        self.current_index = -1
        self.update_status_bar()
        self.setWindowTitle("画像ビューア")

    def delete_current_image_and_load_next(self):
        """現在の画像をごみ箱に移動し、次の画像を読み込む"""
        if self.is_loading or not self.image_files:
            return

        source_path = self.image_files[self.current_index]

        try:
            # 3. ファイルをごみ箱に移動
            print(f"ごみ箱へ移動: {source_path}")
            send2trash(source_path)
            
            # 4. メモリ上のリストから移動したファイルを削除 (moveメソッドと同じロジック)
            self.image_files.pop(self.current_index)
            
            # 5. 次に表示する画像を決定
            if not self.image_files:
                self._clear_display()
            else:
                if self.current_index >= len(self.image_files):
                    self.current_index = 0
                self.load_image_by_index()

        except Exception as e:
            print(f"ファイルの削除に失敗しました: {e}")
            self.statusBar().showMessage(f"エラー: ファイルの削除に失敗しました", 5000)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app_icon_path = resource_path("app_icon.ico")
    app_icon = QIcon(app_icon_path)
    app.setWindowIcon(app_icon)

    viewer = ImageViewer()
    if len(sys.argv) > 1:
        # 最初の引数 (インデックス1) をファイルパスとして読み込む
        initial_file_path = sys.argv[1]
        viewer.load_image_from_path(initial_file_path)
    
    viewer.show()
    sys.exit(app.exec())