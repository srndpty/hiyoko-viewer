"""バックグラウンドスレッドで画像とファイルリストを読み込むワーカー。"""

from __future__ import annotations

import logging
import os
from importlib import import_module
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColorSpace, QImage, QImageReader

logger = logging.getLogger(__name__)


def _load_jxl_with_imagecodecs(file_path: str) -> QImage:
    """Qt の JPEG XL プラグインが無い環境向けに imagecodecs で読み込む。

    用途は JPEG XL に限定されるため、汎用ディスパッチャ ``imread`` ではなく
    JXL デコーダを直接呼ぶ。埋め込みプロファイルは引き継がず、sRGB 相当として
    表示する（広色域 JXL では Qt 経由と色が変わり得る）。
    """
    imagecodecs = import_module("imagecodecs")
    np = import_module("numpy")

    # JPEG XL は複数フレーム（アニメーション）を持てる。index 既定の None だと
    # 全フレームを (frames, h, w, c) で返し後段の形状判定で失敗するため、
    # 静止表示として先頭フレームのみを取得する。
    array = imagecodecs.jpegxl_decode(Path(file_path).read_bytes(), index=0)
    if array is None:
        return QImage()

    array = _as_uint8_array(array, np)

    if array.ndim == 2:
        return _qimage_from_grayscale_array(array, np)

    if array.ndim != 3:
        logger.warning("unsupported JPEG XL array shape: %s", array.shape)
        return QImage()

    channels = array.shape[2]
    if channels == 1:
        return _qimage_from_grayscale_array(array[:, :, 0], np)
    if channels == 2:
        gray = array[:, :, 0]
        alpha = array[:, :, 1]
        array = np.dstack((gray, gray, gray, alpha))
        image_format = QImage.Format.Format_RGBA8888
    elif channels == 3:
        image_format = QImage.Format.Format_RGB888
    elif channels == 4:
        image_format = QImage.Format.Format_RGBA8888
    else:
        logger.warning("unsupported JPEG XL channel count: %s", channels)
        return QImage()

    contiguous = np.ascontiguousarray(array)
    height, width, _ = contiguous.shape
    bytes_per_line = contiguous.strides[0]
    image = QImage(contiguous.data, width, height, bytes_per_line, image_format).copy()
    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    return image


def _as_uint8_array(array, np):
    if array.dtype != np.uint8:
        if array.dtype.kind == "f":
            array = np.clip(array, 0.0, 1.0) * 255.0
        elif array.dtype == np.uint16:
            array = array / 257
        array = np.clip(array, 0, 255).astype(np.uint8)
    return array


def _qimage_from_grayscale_array(array, np) -> QImage:
    contiguous = np.ascontiguousarray(array)
    height, width = contiguous.shape
    bytes_per_line = contiguous.strides[0]
    image = QImage(
        contiguous.data,
        width,
        height,
        bytes_per_line,
        QImage.Format.Format_Grayscale8,
    ).copy()
    image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    return image


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

        if image.isNull() and file_path.lower().endswith(".jxl"):
            logger.debug("Qt failed to load JPEG XL, trying imagecodecs fallback: %s", file_path)
            try:
                image = _load_jxl_with_imagecodecs(file_path)
            except Exception:
                logger.exception("failed to load JPEG XL fallback: %s", file_path)

        # fallback まで含めて読めなかった場合のみ警告する（成功時の誤検知を防ぐ）
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
