"""バックグラウンドスレッドで画像とファイルリストを読み込むワーカー。"""

from __future__ import annotations

import logging
import os

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QImageReader

logger = logging.getLogger(__name__)


class ImageLoader(QObject):
    # QPixmap は GUI リソースで GUI スレッド専用のため、worker では QImage までに留め、
    # QPixmap への変換は受信側（GUI スレッド）の update_image_display で行う。
    image_loaded = pyqtSignal(int, str, QImage)  # (generation, file_path, image)
    list_loaded = pyqtSignal(int, list, int)  # (generation, file_list, initial_index)

    def __init__(self) -> None:
        super().__init__()

    @pyqtSlot(int, str)
    def load_image(self, generation: int, file_path: str) -> None:
        # QImageReader だと失敗理由（未対応フォーマット/破損/権限等）を errorString で残せる
        reader = QImageReader(file_path)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            logger.warning("failed to load image: %s error=%s", file_path, reader.errorString())
        self.image_loaded.emit(generation, file_path, image)

    @pyqtSlot(int, str, str)
    def load_file_list(self, generation: int, directory: str, target_path: str) -> None:
        """指定されたディレクトリをスキャンし、ファイルリストと初期インデックスを返す"""
        from ..config.constants import SUPPORTED_EXTENSIONS

        try:
            # 表示にもそのまま使うため、元の大文字小文字を保持したパスを返す。
            # 並び順は呼び出し側 (ImageViewer) が Windows 論理順で決めるので、ここではソートしない。
            file_list = [
                os.path.join(directory, f)
                for f in os.listdir(directory)
                if f.lower().endswith(tuple(SUPPORTED_EXTENSIONS))
            ]
            # 比較は大文字小文字を無視して行う（target_path は呼び出し側で正規化済み）
            initial_index = next(
                (
                    i
                    for i, path in enumerate(file_list)
                    if os.path.normcase(os.path.normpath(path)) == target_path
                ),
                0,
            )

            self.list_loaded.emit(generation, file_list, initial_index)
        except Exception:
            logger.exception("ファイルリストの読み込みに失敗: directory=%s", directory)
            self.list_loaded.emit(generation, [], -1)
