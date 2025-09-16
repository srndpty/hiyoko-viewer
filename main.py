import sys
import os
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QFileDialog
from PyQt6.QtGui import QPixmap, QKeyEvent
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QThread, pyqtSignal, QObject


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
        # ... (ステップ1の __init__ の中身はほぼ同じ) ...
        self.setWindowTitle("画像ビューア")
        self.setGeometry(100, 100, 800, 600)

        self.image_label = QLabel("ファイル > 開く(Ctrl+O) で画像を選択")
        self.image_label.setScaledContents(True)
        self.setCentralWidget(self.image_label)

        # 画像ファイルのリストと現在のインデックス
        self.image_files = []
        self.current_index = -1
        
        # メニューバーを追加
        menu = self.menuBar()
        file_menu = menu.addMenu("ファイル")
        open_action = file_menu.addAction("開く")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_image)


    def open_image(self):
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
        if not (0 <= self.current_index < len(self.image_files)):
            return

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
        # このメソッドはメインスレッドで実行される
        if pixmap.isNull():
            self.image_label.setText("画像の読み込みに失敗しました")
        else:
            self.image_label.setPixmap(pixmap)
        
        # タイトルを更新
        file_path = self.image_files[self.current_index]
        self.setWindowTitle(f"{os.path.basename(file_path)} ({self.current_index + 1}/{len(self.image_files)})")

    # キーが押されたときのイベントを処理
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Right:
            if self.current_index < len(self.image_files) - 1:
                self.current_index += 1
                self.load_image_by_index()
        elif event.key() == Qt.Key.Key_Left:
            if self.current_index > 0:
                self.current_index -= 1
                self.load_image_by_index()
        else:
            super().keyPressEvent(event) # 他のキーは親クラスに処理を任せる


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = ImageViewer()
    viewer.show()
    sys.exit(app.exec())