import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFileDialog, QPushButton, QVBoxLayout, QWidget
)
from PyQt6.QtGui import QPixmap

class ImageViewer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("シンプル画像ビューア")
        self.setGeometry(100, 100, 800, 600)

        # 画像を表示するためのラベル
        self.image_label = QLabel("画像ファイルを開いてください")
        self.image_label.setScaledContents(True) # ラベルサイズに合わせて画像をスケーリング

        # ファイルを開くボタン
        self.open_button = QPushButton("ファイルを開く")
        self.open_button.clicked.connect(self.open_image)

        # ウィジェットを配置
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        layout.addWidget(self.image_label)
        layout.addWidget(self.open_button)

        self.setCentralWidget(central_widget)

    def open_image(self):
        # ファイルダイアログを開く
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "画像ファイルを開く",
            "",
            "画像ファイル (*.png *.jpg *.jpeg *.bmp)"
        )

        if file_path:
            # QPixmapを使って画像を読み込み、ラベルに設定
            pixmap = QPixmap(file_path)
            self.image_label.setPixmap(pixmap)
            self.setWindowTitle(file_path) # ウィンドウタイトルにファイルパスを表示

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = ImageViewer()
    viewer.show()
    sys.exit(app.exec())