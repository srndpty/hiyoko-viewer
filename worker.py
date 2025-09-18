from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import pyqtSignal, QObject, pyqtSlot

class ImageLoader(QObject):
    finished = pyqtSignal(QPixmap)

    def __init__(self) -> None:
        super().__init__()

    @pyqtSlot(str)
    def load_image(self, file_path: str) -> None:
        pixmap = QPixmap(file_path)
        self.finished.emit(pixmap)