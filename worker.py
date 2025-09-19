from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import pyqtSignal, QObject, pyqtSlot
import os

class ImageLoader(QObject):
    image_loaded = pyqtSignal(QPixmap)
    # ★ 修正点 1: 新しいシグナルを追加
    # [ファイルリスト, 該当ファイルのインデックス] をメインスレッドに返す
    list_loaded = pyqtSignal(list, int)

    def __init__(self) -> None:
        super().__init__()

    @pyqtSlot(str)
    def load_image(self, file_path: str) -> None:
        pixmap = QPixmap(file_path)
        self.image_loaded.emit(pixmap)
        
    # ★ 修正点 2: 新しいスロットを追加
    @pyqtSlot(str, str)
    def load_file_list(self, directory: str, target_path: str) -> None:
        """指定されたディレクトリをスキャンし、ファイルリストと初期インデックスを返す"""
        from constants import SUPPORTED_EXTENSIONS # ローカルでインポート
        
        try:
            sorted_list = sorted([
                os.path.normcase(os.path.join(directory, f)) 
                for f in os.listdir(directory) if f.lower().endswith(tuple(SUPPORTED_EXTENSIONS))
            ])
            initial_index = sorted_list.index(target_path) if target_path in sorted_list else 0
            
            self.list_loaded.emit(sorted_list, initial_index)
        except Exception as e:
            print(f"ファイルリストの読み込みに失敗: {e}")
            self.list_loaded.emit([], -1) # エラー時は空のリストを返す