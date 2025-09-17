import sys
import os
import shutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFileDialog, QSizePolicy, QScrollArea
)
from PyQt6.QtGui import QPixmap, QKeyEvent, QCursor
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QMovie

# 画像をバックグラウンドで読み込むためのワーカースレッド
class ImageLoader(QObject):
    # 読み込み完了時にQPixmapを渡すシグナル
    finished = pyqtSignal(QPixmap)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        # ここが別スレッドで実行される重い処理
        pixmap = QPixmap(self.file_path)
        # 処理が終わったらシグナルを発信
        self.finished.emit(pixmap)

class ImageViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("画像ビューア")
        self.setGeometry(100, 100, 800, 600)

        # --- 状態管理フラグ ---
        self.fit_to_window = True
        self.is_loading = False
        self.original_pixmap = QPixmap()
        
        # ★ 修正点 1: パン操作用のフラグと変数を追加
        self.space_key_pressed = False
        self.is_panning = False
        self.pan_last_mouse_pos = None

        # ★ 修正点 1: ズーム率を管理する変数を追加
        self.scale_factor = 1.0
        self.current_filesize = 0
        self.current_movie = None

        # --- ウィジェットのセットアップ ---
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ★ 修正点 2: QScrollArea を導入
        self.scroll_area = QScrollArea()
        # scroll_areaが表示するウィジェット(QLabel)が、表示領域より小さい場合に
        # 中央に配置するように設定する
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setWidgetResizable(True) # フィット表示時に重要
        # ホイールイベントはviewportで横取りする
        self.scroll_area.viewport().installEventFilter(self)
        # キーイベントはscroll_area本体で横取りする
        self.scroll_area.installEventFilter(self)
        self.setCentralWidget(self.scroll_area)

        # ... (メニューバー設定は変更なし) ...
        self.image_files = []
        self.current_index = -1
        menu = self.menuBar()
        file_menu = menu.addMenu("ファイル")
        open_action = file_menu.addAction("開く")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_image)

        self.setAcceptDrops(True)

    def load_image_from_path(self, file_path):
        """指定されたファイルパスから画像を読み込む"""
        if not file_path:
            return

        directory = os.path.dirname(file_path)
        all_files = os.listdir(directory)
        
        supported_extensions = [
            '.bmp', '.cur', '.gif', '.ico', '.icns', '.jpeg', '.jpg', '.pbm', 
            '.pgm', '.png', '.ppm', '.svg', '.svgz', '.tga', '.tif', '.tiff', 
            '.wbmp', '.webp', '.xbm', '.xpm'
        ]

        self.image_files = sorted([
            os.path.normcase(os.path.join(directory, f)) 
            for f in all_files if f.lower().endswith(tuple(supported_extensions))
        ])
        
        normalized_path = os.path.normcase(os.path.normpath(file_path))
        try:
            self.current_index = self.image_files.index(normalized_path)
            self.load_image_by_index()
        except ValueError:
            print(f"エラー: 正規化されたパス '{normalized_path}' がリストに見つかりませんでした。")
            self.image_label.setText("画像の読み込みに失敗しました。")

    def update_status_bar(self):
        if self.original_pixmap.isNull():
            self.statusBar().clearMessage()
            return

        w = self.original_pixmap.width()
        h = self.original_pixmap.height()
        fs_mb = f"{self.current_filesize / (1024*1024):.2f}MB"
        
        zoom_percent = 0.0
        if self.fit_to_window:
            # フィットモードの場合、現在の表示倍率を計算
            if w > 0 and h > 0:
                vp_size = self.scroll_area.viewport().size()
                scale_w = vp_size.width() / w
                scale_h = vp_size.height() / h
                zoom_percent = min(scale_w, scale_h) * 100
        else:
            # ズームモードの場合
            zoom_percent = self.scale_factor * 100
        
        mode_str = "フィット" if self.fit_to_window else "フリー"
        status_text = f"サイズ: {w} x {h}  |  ファイルサイズ: {fs_mb}  |  ズーム: {zoom_percent:.1f}%  |  モード: {mode_str}"
        # もしムービーがロードされていれば、再生状態を追加
        if self.current_movie and self.current_movie.isValid():
            # GIFの再生状態とフレーム情報を表示
            state_str = ""
            if self.current_movie.state() == QMovie.MovieState.Paused:
                state_str = " [一時停止]"
            elif self.current_movie.state() == QMovie.MovieState.Running:
                state_str = " [再生中]"
            
            frame_info = f" [フレーム: {self.current_movie.currentFrameNumber() + 1}/{self.current_movie.frameCount()}]"
            status_text += state_str + frame_info
        self.statusBar().showMessage(status_text)

    def move_current_image_and_load_next(self, subfolder_name):
        """現在の画像をサブフォルダに移動し、次の画像を読み込む"""
        if self.is_loading or not self.image_files:
            return

        # 1. 移動元と移動先のパスを準備
        source_path = self.image_files[self.current_index]
        directory = os.path.dirname(source_path)
        dest_folder = os.path.join(directory, subfolder_name)
        dest_path = os.path.join(dest_folder, os.path.basename(source_path))

        # 2. 移動先のフォルダがなければ作成
        os.makedirs(dest_folder, exist_ok=True)

        try:
            # 3. ファイルを移動
            print(f"移動中: {source_path} -> {dest_path}")
            shutil.move(source_path, dest_path)
            
            # 4. メモリ上のリストから移動したファイルを削除
            self.image_files.pop(self.current_index)
            
            # 5. 次に表示する画像を決定
            if not self.image_files:
                # リストが空になったら、表示をクリア
                self.stop_movie()
                self.original_pixmap = QPixmap()
                self.image_label.clear()
                self.current_index = -1
                self.update_status_bar()
                self.setWindowTitle("画像ビューア")
            else:
                # リストの最後にあった画像を移動した場合、インデックスを0に戻す
                if self.current_index >= len(self.image_files):
                    self.current_index = 0
                
                # インデックスはそのままで、次の画像をロード
                # (popしたので、現在のインデックスが事実上「次の画像」を指しているため)
                self.load_image_by_index()

        except Exception as e:
            print(f"ファイルの移動に失敗しました: {e}")
            self.statusBar().showMessage(f"エラー: ファイルの移動に失敗しました", 5000) # 5秒間表示

    def eventFilter(self, source, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            print(f"KeyPress: {key}") # デバッグ用

        # イベントの発生元がscroll_areaかチェック
        if source is self.scroll_area.viewport():
            if event.type() == QEvent.Type.Wheel:
                if self.is_loading:
                    return True # 読み込み中はイベントを消費

                # 修飾キーを取得
                modifiers = event.modifiers()
                # ホイールの回転量
                angle_delta = event.angleDelta().y()
                scroll_amount = angle_delta // 120 * 40

                # ★ 修正点 3: Ctrl+ホイールの処理を追加
                if modifiers == Qt.KeyboardModifier.ControlModifier:
                    # もしフィットモードからズームを開始する場合、現在のフィット倍率を計算して初期値とする
                    if self.fit_to_window:
                        if self.original_pixmap.isNull() or self.original_pixmap.width() == 0:
                            return True # 画像がない場合は何もしない
                        
                        pixmap_size = self.original_pixmap.size()
                        viewport_size = self.scroll_area.viewport().size()
                        
                        # 幅基準と高さ基準のスケールを計算し、小さい方（フィットしている方）を採用
                        scale_w = viewport_size.width() / pixmap_size.width()
                        scale_h = viewport_size.height() / pixmap_size.height()
                        current_fit_scale = min(scale_w, scale_h)
                        
                        # 計算したフィット倍率を現在のスケールとして設定
                        self.scale_factor = current_fit_scale
                        
                        # 手動ズームモードに移行
                        self.fit_to_window = False
                    # 1. ズーム前の情報を記録
                    old_scale_factor = self.scale_factor
                    
                    # ★★★ ここを .position() に修正 ★★★
                    mouse_pos = event.position()
                    
                    h_bar = self.scroll_area.horizontalScrollBar()
                    v_bar = self.scroll_area.verticalScrollBar()
                    h_scroll_before = h_bar.value()
                    v_scroll_before = v_bar.value()

                    # 2. 新しいズーム率を計算
                    if angle_delta > 0:
                        self.scale_factor *= 1.15
                    else:
                        self.scale_factor /= 1.15
                    
                    self.fit_to_window = False
                    
                    # 3. UIを更新
                    self.redraw_image()
                    
                    # 4. 新しいスクロール位置を計算 (以降のロジックは変更不要)
                    abs_x_before = h_scroll_before + mouse_pos.x()
                    abs_y_before = v_scroll_before + mouse_pos.y()
                    
                    abs_x_after = abs_x_before * (self.scale_factor / old_scale_factor)
                    abs_y_after = abs_y_before * (self.scale_factor / old_scale_factor)
                    
                    new_h_scroll = abs_x_after - mouse_pos.x()
                    new_v_scroll = abs_y_after - mouse_pos.y()
                    
                    # 5. スクロールバーを新しい位置にセット
                    h_bar.setValue(int(new_h_scroll))
                    v_bar.setValue(int(new_v_scroll))
                    self.update_status_bar()

                    return True
                
                elif modifiers == Qt.KeyboardModifier.ShiftModifier:
                    # Shiftキーが押されていたら、水平スクロール
                    h_bar = self.scroll_area.horizontalScrollBar()
                    h_bar.setValue(h_bar.value() - scroll_amount)
                    print(f"水平スクロール: {scroll_amount}") # デバッグ用
                    return True # ★重要: イベントを消費し、デフォルト動作を防ぐ
                else:
                    # Shiftキーが押されていなければ、垂直スクロール
                    v_bar = self.scroll_area.verticalScrollBar()
                    v_bar.setValue(v_bar.value() - scroll_amount)
                    print(f"垂直スクロール: {scroll_amount}") # デバッグ用
                    return True # ★重要: イベントを消費
            elif event.type() == QEvent.Type.MouseButtonPress:
                # 左クリックの場合のみ反応
                if event.button() == Qt.MouseButton.LeftButton:
                    # GIFが表示されている場合のみ処理
                    if self.current_movie and self.current_movie.isValid():
                        # 再生状態に応じてトグル
                        if self.current_movie.state() == QMovie.MovieState.Running:
                            self.current_movie.setPaused(True)
                        elif self.current_movie.state() == QMovie.MovieState.Paused:
                            self.current_movie.setPaused(False) # setPaused(False)で再開
                        
                        # ステータスバーを更新して状態をフィードバック
                        self.update_status_bar()
                        
                        return True # イベントを消費

        # キーイベントが scroll_area 本体に行くケースも考慮
        if source is self.scroll_area and event.type() == QEvent.Type.KeyPress:
            if self.is_loading: return True
            key = event.key()
            modifiers = event.modifiers()

            # KeypadModifier をチェックして、テンキーからの入力であることを確認
            if modifiers & Qt.KeyboardModifier.KeypadModifier:
                if key == Qt.Key.Key_9:
                    self.move_current_image_and_load_next("_ok")
                    return True
                elif key == Qt.Key.Key_7:
                    self.move_current_image_and_load_next("_ng")
                    return True
                
            if key == Qt.Key.Key_Right or key == Qt.Key.Key_PageDown:
                self.show_next_image(); return True
            elif key == Qt.Key.Key_Left or key == Qt.Key.Key_PageUp:
                self.show_prev_image(); return True
            elif key == Qt.Key.Key_Period:
                # GIFが表示されている場合のみ処理
                if self.current_movie and self.current_movie.isValid() and self.current_movie.frameCount() > 0:
                    current_frame = self.current_movie.currentFrameNumber()
                    total_frames = self.current_movie.frameCount()
                    new_frame = (current_frame + 1) % total_frames
                    
                    self.current_movie.jumpToFrame(new_frame)
                    self.current_movie.setPaused(True)
                    self.update_status_bar()
                    return True # イベントを消費
        # 上記の条件に当てはまらない場合は、デフォルトのイベント処理に任せる
        return super().eventFilter(source, event)
    
    # ★ 修正点 3: コードの重複を避けるためにヘルパーメソッドを作成
    def show_next_image(self):
        if self.is_loading or not self.image_files:
            return

        self.current_index = (self.current_index + 1) % len(self.image_files)
        self.load_image_by_index()

    def show_prev_image(self):
        if self.is_loading or not self.image_files:
            return
        
        self.current_index = (self.current_index - 1) % len(self.image_files)
        self.load_image_by_index()

    def open_image(self):
        # すでに読み込み中なら無視
        if self.is_loading:
            return
        
        supported_extensions = [
            '.bmp', '.cur', '.gif', '.icns', '.ico', '.jfif', '.jpeg', '.jpg', 
            '.pbm', '.pdf', '.pgm', '.png', '.ppm', '.svg', '.svgz', '.tga', 
            '.tif', '.tiff', '.wbmp', '.webp', '.xbm', '.xpm'
        ]

        filter_extensions = " ".join([f"*.{ext[1:]}" for ext in supported_extensions])
        dialog_filter = f"対応画像ファイル ({filter_extensions});;すべてのファイル (*)"

        file_path, _ = QFileDialog.getOpenFileName(self, "画像ファイルを開く", "", dialog_filter)

        self.load_image_from_path(file_path)

    # ★ 修正点 4: dragEnterEvent をオーバーライド
    def dragEnterEvent(self, event):
        """ファイルがウィンドウ上にドラッグされたときに呼ばれる"""
        # ドロップされようとしているデータにURL(ファイルパス)が含まれているかチェック
        if event.mimeData().hasUrls():
            # 含まれていれば、ドロップ操作を受け入れる
            event.acceptProposedAction()
        else:
            # そうでなければ、通常通りの処理
            super().dragEnterEvent(event)

    # ★ 修正点 5: dropEvent をオーバーライド
    def dropEvent(self, event):
        """ファイルがウィンドウ上でドロップされたときに呼ばれる"""
        # ドロップされたURL(ファイルパス)のリストを取得
        urls = event.mimeData().urls()
        if urls:
            # 複数のファイルがドロップされた場合も、最初のファイルだけを対象にする
            file_path = urls[0].toLocalFile()
            
            # 共通メソッドを呼び出して画像を読み込む
            self.load_image_from_path(file_path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def update_gif_frame_status(self, frame_number):
        """GIFのフレームが変更されるたびにステータスバーを更新するための軽量なスロット"""
        if self.current_movie and self.current_movie.isValid():
            self.update_status_bar()

    def stop_movie(self):
        """現在再生中のムービーがあれば停止し、リソースを解放する"""
        if self.current_movie:
            # ★ 修正点 2: シグナルの接続をすべて解除する
            try:
                # 引数なしでdisconnect()を呼ぶと、このシグナルに接続された全てのスロットを解除する
                self.current_movie.frameChanged.disconnect()
            except TypeError:
                pass # 接続がなかった場合のエラーを無視
            self.current_movie.stop()
            self.current_movie = None
        self.image_label.setMovie(None)
    
    def load_image_by_index(self):
        # すでに読み込み中なら無視
        if self.is_loading:
            return
        if not (0 <= self.current_index < len(self.image_files)):
            return
        
        self.stop_movie()
        # 新しい画像を読み込む直前に、表示モードとズーム率をリセットする
        self.fit_to_window = True
        self.scale_factor = 1.0
        self.is_loading = True
        print(f"Loading image at index {self.current_index}") # デバッグ用

        file_path = self.image_files[self.current_index]
        try:
            self.current_filesize = os.path.getsize(file_path)
        except OSError:
            self.current_filesize = 0
        
        self.setWindowTitle(f"読み込み中... {os.path.basename(file_path)}")
        self.image_label.setText("読み込み中...") # UIは固まらないことをユーザーに示す

        # --- 非同期読み込みのセットアップ ---
        self.thread = QThread()
        self.worker = ImageLoader(file_path)
        self.worker.moveToThread(self.thread)

        # スレッドが開始したらworkerのrunを実行
        self.thread.started.connect(self.worker.run)
        # workerが終わったらスレッドを終了し、後片付け
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        # workerのfinishedシグナルを、画像を表示するメソッドに接続
        self.worker.finished.connect(self.update_image_display)

        # スレッドを開始！
        self.thread.start()

    def on_gif_first_frame(self, frame_number):
        # print("-" * 20)
        # print(f"on_gif_first_frame CALLED for frame number: {frame_number}")
        
        if not self.current_movie:
            print("  -> ERROR: self.current_movie is None. Aborting.")
            print("-" * 20)
            return
        
        # print(f"  - self.current_movie is valid: {self.current_movie is not None}")
        
        first_frame_pixmap = self.current_movie.currentPixmap()
        is_pixmap_null = first_frame_pixmap.isNull()
        
        # print(f"  - first_frame_pixmap.isNull(): {is_pixmap_null}")

        if not is_pixmap_null:
            # print("  -> LOGIC BLOCK ENTERED: Pixmap is valid. Updating display.")
            self.original_pixmap = first_frame_pixmap
            
            try:
                self.current_movie.frameChanged.disconnect(self.on_gif_first_frame)
                # print("  -> Disconnect successful.")
            except TypeError:
                print("  -> Already disconnected or failed to disconnect.")

            self.redraw_image()
            self.update_status_bar()
        else:
            print("  -> LOGIC BLOCK SKIPPED: Pixmap is still null.")

        # print("-" * 20)

    def update_image_display(self, pixmap):
        file_path = self.image_files[self.current_index]

        # ★ 修正点 4: ファイルの種類に応じて処理を分岐
        if file_path.lower().endswith('.gif'):
            self.current_movie = QMovie(file_path)
            
            # 1. 一度だけ実行したい、重い初期化処理
            self.current_movie.frameChanged.connect(self.on_gif_first_frame)
            # 2. 毎フレーム実行したい、軽いステータス更新処理
            self.current_movie.frameChanged.connect(self.update_gif_frame_status)
            
            self.image_label.setMovie(self.current_movie)
            self.current_movie.start()
            
            # ここではまだ正しいサイズがわからないので、一旦何もしない
            # 最初のフレームが準備できたら、on_gif_first_frame が後処理をしてくれる
        else:
            # --- 静止画の場合 (従来通り) ---
            if pixmap.isNull():
                self.image_label.setText("画像の読み込みに失敗しました")
                self.original_pixmap = QPixmap()
            else:
                self.original_pixmap = pixmap
                
        self.redraw_image()
        self.setWindowTitle(f"[{self.current_index + 1}/{len(self.image_files)}] {os.path.basename(file_path)}")
        self.update_status_bar()
        self.is_loading = False

    # ★ 修正点 3: 新しいメソッドを追加
    def redraw_image(self):
        """現在の表示モード（フィット/原寸）に応じて画像を描画する"""
        if self.original_pixmap.isNull():
            return

        # ★ 修正点 5: 描画ロジックをGIFと静止画で完全に分岐
        if self.current_movie and self.current_movie.isValid():
            # --- GIFアニメの再描画ロジック ---
            self.image_label.setScaledContents(True) # ムービーをラベルサイズに追従させる

            if self.fit_to_window:
                # --- フィット表示モード ---
                self.scroll_area.setWidgetResizable(False) # 手動でサイズ設定するのでFalseにする
                
                # 1. 静止画と同じロジックで、フィット表示の目標サイズを計算
                scaled_pixmap = self.original_pixmap.scaled(
                    self.scroll_area.viewport().size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                target_size = scaled_pixmap.size()

                # 2. QLabelのサイズを、計算した目標サイズに強制的に固定する
                self.image_label.setFixedSize(target_size)
                
                # 3. サイズが確定したラベルにムービーをセットして再生
                self.image_label.setMovie(self.current_movie)
                if not self.current_movie.state() == QMovie.MovieState.Running:
                    self.current_movie.start()
            else:
                # --- ズーム表示モード ---
                self.scroll_area.setWidgetResizable(False)
                scaled_size = self.original_pixmap.size() * self.scale_factor
                self.image_label.setFixedSize(scaled_size)
                
                # ムービーがセットされていない場合（ズーム操作が先に行われた場合など）を考慮
                if self.image_label.movie() is not self.current_movie:
                    self.image_label.setMovie(self.current_movie)
                if not self.current_movie.state() == QMovie.MovieState.Running:
                    self.current_movie.start()
        else:
            # --- 静止画の再描画ロジック (従来通り) ---
            # 静止画の場合、ラベルのサイズは可変であるべきなので、固定を解除する
            self.image_label.setMinimumSize(1, 1)
            self.image_label.setMaximumSize(16777215, 16777215) # QWidgetの最大サイズ
            self.image_label.setScaledContents(False)

            if self.fit_to_window:
                self.scroll_area.setWidgetResizable(True)
                scaled_pixmap = self.original_pixmap.scaled(
                    self.scroll_area.viewport().size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
            else:
                self.scroll_area.setWidgetResizable(False)
                scaled_pixmap = self.original_pixmap.scaled(
                    int(self.original_pixmap.width() * self.scale_factor),
                    int(self.original_pixmap.height() * self.scale_factor),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
                self.image_label.adjustSize()

    # ★ 修正点 4: ウィンドウのリサイズイベントをオーバーライド
    def resizeEvent(self, event):
        """ウィンドウがリサイズされたときに呼び出される"""
        super().resizeEvent(event)

        # ウィンドウリサイズ時はフィット表示モードの時だけ再描画すれば良い
        if self.fit_to_window:
            self.redraw_image()

    # キーが押されたときのイベントを処理
    def keyPressEvent(self, event: QKeyEvent):
        # すでに読み込み中なら無視
        if self.is_loading:
            event.ignore() # イベントを無視する
            return
        
        key = event.key()

        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_key_pressed = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

        elif key == Qt.Key.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()

        elif key == Qt.Key.Key_Escape:
            self.close()

        elif key == Qt.Key.Key_F:
            if self.fit_to_window:
                self.fit_to_window = False
                self.scale_factor = 1.0
            else:
                self.fit_to_window = True
            self.redraw_image()
            self.update_status_bar()
            
        else:
            super().keyPressEvent(event)

    # ★ 修正点 6: キーが離されたときのイベントハンドラを追加
    def keyReleaseEvent(self, event: QKeyEvent):
        if not event.isAutoRepeat() and event.key() == Qt.Key.Key_Space:
            self.space_key_pressed = False
            self.is_panning = False # パン操作も強制終了
            self.unsetCursor() # カーソルを元に戻す
        else:
            super().keyReleaseEvent(event)

    # ★ 修正点 7: マウスイベントハンドラを3つ追加
    def mousePressEvent(self, event):
        # 原寸表示モード かつ スペースキーが押されている場合のみパン開始
        if not self.fit_to_window and self.space_key_pressed:
            if event.button() == Qt.MouseButton.LeftButton:
                self.is_panning = True
                self.pan_last_mouse_pos = event.pos()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_panning:
            # マウスの移動量に応じてスクロールバーを動かす
            delta = event.pos() - self.pan_last_mouse_pos
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            self.pan_last_mouse_pos = event.pos()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_panning:
            self.is_panning = False
            # スペースキーがまだ押されていればOpenHandに、離されていれば元に戻す
            if self.space_key_pressed:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self.unsetCursor()
        else:
            super().mouseReleaseEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = ImageViewer()
    viewer.show()
    sys.exit(app.exec())