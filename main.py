import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFileDialog, QSizePolicy, QScrollArea
)
from PyQt6.QtGui import QPixmap, QKeyEvent, QCursor
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QEvent

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
        # ★ 修正点 1: scroll_areaにイベントフィルターをインストール
        # これにより、scroll_area宛のイベントがeventFilterメソッドに送られるようになる
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

    # ★ 修正点 2: イベントフィルターの本体を実装
    def eventFilter(self, source, event):
        # イベントの発生元がscroll_areaで、かつキーが押されたイベントかチェック
        if source is self.scroll_area and event.type() == QEvent.Type.KeyPress:
            # 読み込み中は何も受け付けない
            if self.is_loading:
                return True # イベントを消費して伝播を止める

            key = event.key()
            # 左右キーだったら、画像切り替え処理を呼び出す
            if key == Qt.Key.Key_Right:
                self.show_next_image()
                return True # イベントを消費して、スクロールバーに渡さない
            elif key == Qt.Key.Key_Left:
                self.show_prev_image()
                return True # イベントを消費して、スクロールバーに渡さない

        # 上記の条件に当てはまらない場合は、デフォルトのイベント処理に任せる
        return super().eventFilter(source, event)
    # ★ 修正点 3: コードの重複を避けるためにヘルパーメソッドを作成
    def show_next_image(self):
        if self.is_loading: return
        if self.current_index < len(self.image_files) - 1:
            self.current_index += 1
            self.load_image_by_index()

    def show_prev_image(self):
        if self.is_loading: return
        if self.current_index > 0:
            self.current_index -= 1
            self.load_image_by_index()

    def open_image(self):
        # すでに読み込み中なら無視
        if self.is_loading:
            return
        
        file_path, _ = QFileDialog.getOpenFileName(self, "画像ファイルを開く", "", "画像ファイル (*.png *.jpg *.jpeg *.bmp)")

        if file_path:
            directory = os.path.dirname(file_path)
            all_files = os.listdir(directory)
            
            image_extensions = ['.png', '.jpg', '.jpeg', '.bmp']

            # ★修正点1: リストを作成する際に、各パスをnormcaseで正規化する
            self.image_files = sorted([
                os.path.normcase(os.path.join(directory, f)) 
                for f in all_files if f.lower().endswith(tuple(image_extensions))
            ])
            
            # ★修正点2: 検索する側のパスもnormpathに加えてnormcaseで正規化する
            normalized_path = os.path.normcase(os.path.normpath(file_path))

            # --- ここからデバッグ用のprint文を追加 ---
            # print("--- デバッグ情報 ---")
            # print(f"検索する正規化済みパス: {normalized_path}")
            # print("検索対象リストの中身:")
            # for p in self.image_files:
            #     print(p) # リストの中身を一つずつ全部表示してみる
            # print("--------------------")
            
            self.current_index = self.image_files.index(normalized_path)
            self.load_image_by_index()

    def load_image_by_index(self):
        # すでに読み込み中なら無視
        if self.is_loading:
            return
        
        if not (0 <= self.current_index < len(self.image_files)):
            return

        self.is_loading = True

        file_path = self.image_files[self.current_index]
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

    def update_image_display(self, pixmap):
        if pixmap.isNull():
            self.image_label.setText("画像の読み込みに失敗しました")
            self.original_pixmap = QPixmap()
        else:
            self.original_pixmap = pixmap
            self.redraw_image()

        file_path = self.image_files[self.current_index]
        self.setWindowTitle(f"{os.path.basename(file_path)} ({self.current_index + 1}/{len(self.image_files)})")
        self.is_loading = False


    # ★ 修正点 3: 新しいメソッドを追加
    def redraw_image(self):
        """現在の表示モード（フィット/原寸）に応じて画像を描画する"""
        if self.original_pixmap.isNull():
            return

        if self.fit_to_window:
            # --- フィット表示モード ---
            # ★ 修正点 3: フィット表示のロジックを更新
            self.scroll_area.setWidgetResizable(True)
            scaled_pixmap = self.original_pixmap.scaled(
                self.scroll_area.size(), # ラベルではなくスクロールエリアのサイズに合わせる
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)
        else:
            # --- 原寸表示モード ---
            # ★ 修正点 4: 原寸表示のロジックを更新
            self.scroll_area.setWidgetResizable(False)
            self.image_label.setPixmap(self.original_pixmap)
            # ラベルのサイズを画像の原寸に合わせる(重要)
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
        
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_key_pressed = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        
        if event.key() == Qt.Key.Key_F:
            # フラグを反転させる
            self.fit_to_window = not self.fit_to_window
            # 表示を更新する
            self.redraw_image()
        elif event.key() == Qt.Key.Key_Right:
            self.show_next_image()
        elif event.key() == Qt.Key.Key_Left:
            self.show_prev_image()
        else:
            super().keyPressEvent(event) # 他のキーは親クラスに処理を任せる

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