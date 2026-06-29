import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from hiyoko_viewer.config.constants import SUPPORTED_EXTENSIONS
from hiyoko_viewer.services import image_loader
from hiyoko_viewer.services.image_loader import ImageLoader


def _require_jpegxl():
    """実 JPEG XL デコーダが使えない環境ではスキップする。"""
    imagecodecs = pytest.importorskip("imagecodecs")
    if not (hasattr(imagecodecs, "jpegxl_encode") and hasattr(imagecodecs, "jpegxl_decode")):
        pytest.skip("imagecodecs に JPEG XL コーデックが無い")
    return imagecodecs


def test_supported_extensions_include_jpeg_xl() -> None:
    assert ".jxl" in SUPPORTED_EXTENSIONS


def test_load_file_list_emits_supported_images_in_original_case(tmp_path) -> None:
    image_a = tmp_path / "b.PNG"
    image_b = tmp_path / "a.jpg"
    image_c = tmp_path / "c.JXL"
    ignored = tmp_path / "memo.txt"
    image_a.write_bytes(b"fake")
    image_b.write_bytes(b"fake")
    image_c.write_bytes(b"fake")
    ignored.write_text("not an image", encoding="utf-8")

    emitted: list[tuple[int, list[str], int]] = []
    loader = ImageLoader()
    loader.list_loaded.connect(lambda gen, paths, index: emitted.append((gen, paths, index)))

    target_path = os.path.normcase(os.path.normpath(str(image_a)))
    loader.load_file_list(1, str(tmp_path), target_path)

    assert len(emitted) == 1
    gen, paths, index = emitted[0]
    assert gen == 1
    # 表示用に元の大文字小文字を保持したまま返す（並び順は呼び出し側が決める）
    assert set(paths) == {str(image_a), str(image_b), str(image_c)}
    assert paths[index] == str(image_a)


def test_load_file_list_emits_empty_result_for_missing_directory(tmp_path) -> None:
    emitted: list[tuple[int, list[str], int]] = []
    loader = ImageLoader()
    loader.list_loaded.connect(lambda gen, paths, index: emitted.append((gen, paths, index)))

    loader.load_file_list(2, str(tmp_path / "missing"), "missing.png")

    assert emitted == [(2, [], -1)]


def test_load_file_list_uses_first_image_when_target_is_not_in_directory(tmp_path) -> None:
    image_a = tmp_path / "a.png"
    image_b = tmp_path / "b.jpg"
    image_a.write_bytes(b"fake")
    image_b.write_bytes(b"fake")

    emitted: list[tuple[int, list[str], int]] = []
    loader = ImageLoader()
    loader.list_loaded.connect(lambda gen, paths, index: emitted.append((gen, paths, index)))

    target_path = os.path.normcase(os.path.normpath(str(tmp_path / "missing.png")))
    loader.load_file_list(3, str(tmp_path), target_path)

    assert len(emitted) == 1
    gen, paths, index = emitted[0]
    assert gen == 3
    assert set(paths) == {str(image_a), str(image_b)}
    assert index == 0


def test_load_image_falls_back_to_imagecodecs_for_jpeg_xl(monkeypatch, tmp_path) -> None:
    """Qt が読めない JXL で imagecodecs.jpegxl_decode へ制御が渡ることを確認する。"""
    image_path = tmp_path / "photo.jxl"
    image_path.write_bytes(b"not a qt-readable image")
    decoded = np.array(
        [
            [[255, 0, 0], [0, 255, 0]],
            [[0, 0, 255], [255, 255, 255]],
        ],
        dtype=np.uint8,
    )
    calls: list[bytes] = []

    def fake_decode(data, index=None):
        calls.append((data, index))
        return decoded

    monkeypatch.setitem(
        sys.modules,
        "imagecodecs",
        SimpleNamespace(jpegxl_decode=fake_decode),
    )

    emitted = []
    loader = ImageLoader()
    loader.image_loaded.connect(lambda gen, path, image: emitted.append((gen, path, image)))

    loader.load_image(4, str(image_path))

    assert len(emitted) == 1
    gen, path, image = emitted[0]
    assert gen == 4
    assert path == str(image_path)
    assert not image.isNull()
    assert image.width() == 2
    assert image.height() == 2
    # 拡張子で JXL と判定し、ファイルの生バイトと先頭フレーム指定を渡している
    assert calls == [(b"not a qt-readable image", 0)]


@pytest.mark.parametrize(
    ("make_array", "sample"),
    [
        (
            lambda: np.array(
                [[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [10, 20, 30]]],
                dtype=np.uint8,
            ),
            ((1, 1), (10, 20, 30, 255)),
        ),
        (
            lambda: np.dstack(
                [
                    np.array(
                        [[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [10, 20, 30]]],
                        dtype=np.uint8,
                    ),
                    np.array([[200, 150], [100, 50]], dtype=np.uint8),
                ]
            ),
            ((0, 0), (255, 0, 0, 200)),
        ),
        (
            lambda: np.array([[0, 255], [128, 64]], dtype=np.uint8),
            ((0, 1), (128, 128, 128, 255)),
        ),
    ],
    ids=["rgb", "rgba", "grayscale"],
)
def test_load_image_decodes_real_jpeg_xl(monkeypatch, tmp_path, make_array, sample) -> None:
    """実 JPEG XL をロスレス生成し、fallback 経路で正しく読み戻せることを確認する。"""
    imagecodecs = _require_jpegxl()
    array = make_array()
    image_path = tmp_path / "real.jxl"
    image_path.write_bytes(imagecodecs.jpegxl_encode(array, lossless=True))

    # Qt 側に JXL プラグインがある環境でも必ず fallback を通すため、reader を失敗させる。
    class _NullReader:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def setAutoTransform(self, *args, **kwargs) -> None:
            pass

        def read(self):
            from PyQt6.QtGui import QImage

            return QImage()

        def errorString(self) -> str:
            return "forced failure"

    monkeypatch.setattr(image_loader, "QImageReader", _NullReader)

    emitted = []
    loader = ImageLoader()
    loader.image_loaded.connect(lambda gen, path, image: emitted.append((gen, path, image)))

    loader.load_image(5, str(image_path))

    assert len(emitted) == 1
    _gen, _path, image = emitted[0]
    assert not image.isNull()
    assert image.width() == array.shape[1]
    assert image.height() == array.shape[0]

    (x, y), expected_rgba = sample
    assert image.pixelColor(x, y).getRgb() == expected_rgba


def test_load_image_warns_only_when_fallback_also_fails(monkeypatch, tmp_path, caplog) -> None:
    """fallback で読めた場合に 'failed to load image' 警告を出さないことを確認する。"""
    imagecodecs = _require_jpegxl()
    array = np.array([[[255, 0, 0], [0, 255, 0]]], dtype=np.uint8)
    image_path = tmp_path / "ok.jxl"
    image_path.write_bytes(imagecodecs.jpegxl_encode(array, lossless=True))

    class _NullReader:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def setAutoTransform(self, *args, **kwargs) -> None:
            pass

        def read(self):
            from PyQt6.QtGui import QImage

            return QImage()

        def errorString(self) -> str:
            return "forced failure"

    monkeypatch.setattr(image_loader, "QImageReader", _NullReader)

    loader = ImageLoader()
    with caplog.at_level("WARNING", logger=image_loader.logger.name):
        loader.load_image(6, str(image_path))

    assert "failed to load image" not in caplog.text
