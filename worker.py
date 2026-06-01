import logging
import os

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap

logger = logging.getLogger(__name__)


class ImageLoader(QObject):
    image_loaded = pyqtSignal(str, QPixmap)  # (file_path, pixmap)
    list_loaded = pyqtSignal(int, list, int)  # (generation, file_list, initial_index)

    def __init__(self) -> None:
        super().__init__()

    @pyqtSlot(str)
    def load_image(self, file_path: str) -> None:
        pixmap = QPixmap(file_path)
        self.image_loaded.emit(file_path, pixmap)

    @pyqtSlot(int, str, str)
    def load_file_list(self, generation: int, directory: str, target_path: str) -> None:
        """指定されたディレクトリをスキャンし、ファイルリストと初期インデックスを返す"""
        from constants import SUPPORTED_EXTENSIONS  # ローカルでインポート

        try:
            sorted_list = sorted(
                [
                    os.path.normcase(os.path.join(directory, f))
                    for f in os.listdir(directory)
                    if f.lower().endswith(tuple(SUPPORTED_EXTENSIONS))
                ]
            )
            initial_index = sorted_list.index(target_path) if target_path in sorted_list else 0

            self.list_loaded.emit(generation, sorted_list, initial_index)
        except Exception:
            logger.exception("ファイルリストの読み込みに失敗: directory=%s", directory)
            self.list_loaded.emit(generation, [], -1)
