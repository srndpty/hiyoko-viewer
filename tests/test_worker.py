import os
import sys
from types import SimpleNamespace

import numpy as np

from hiyoko_viewer.config.constants import SUPPORTED_EXTENSIONS
from hiyoko_viewer.services.image_loader import ImageLoader


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
    image_path = tmp_path / "photo.jxl"
    image_path.write_bytes(b"not a qt-readable image")
    decoded = np.array(
        [
            [[255, 0, 0], [0, 255, 0]],
            [[0, 0, 255], [255, 255, 255]],
        ],
        dtype=np.uint8,
    )
    monkeypatch.setitem(sys.modules, "imagecodecs", SimpleNamespace(imread=lambda path: decoded))

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
