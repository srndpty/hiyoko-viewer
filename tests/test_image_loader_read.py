"""ImageLoader.load_image の実読み込み経路の検証。

QImageReader は QApplication なしでも画像のデコードができるため、ここでは
実ファイルを生成して「対応形式の読み込み成功 / 破損ファイル / 巨大画像」を確認する。
"""

from __future__ import annotations

import logging

import pytest
from PyQt6.QtGui import QImage

from hiyoko_viewer.services.image_loader import ImageLoader


def _collect_load_image(loader: ImageLoader) -> list[tuple[int, str, QImage]]:
    emitted: list[tuple[int, str, QImage]] = []
    loader.image_loaded.connect(lambda gen, path, image: emitted.append((gen, path, image)))
    return emitted


def _save_image(path, width: int, height: int, color: int = 0xFF3776AB) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(str(path)), f"テスト用画像の生成に失敗: {path}"


@pytest.mark.parametrize("ext", [".png", ".bmp", ".jpg"])
def test_load_image_emits_decoded_image_for_supported_formats(tmp_path, ext) -> None:
    image_path = tmp_path / f"sample{ext}"
    _save_image(image_path, 8, 6)

    loader = ImageLoader()
    emitted = _collect_load_image(loader)

    loader.load_image(7, str(image_path))

    assert len(emitted) == 1
    generation, path, image = emitted[0]
    assert generation == 7
    assert path == str(image_path)
    assert not image.isNull()
    assert (image.width(), image.height()) == (8, 6)


def test_load_image_emits_null_image_for_corrupted_file(tmp_path, caplog) -> None:
    # PNG 拡張子だが中身が画像でない＝デコードに失敗するファイル
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"this is definitely not a PNG")

    loader = ImageLoader()
    emitted = _collect_load_image(loader)

    with caplog.at_level(logging.WARNING):
        loader.load_image(1, str(broken))

    assert len(emitted) == 1
    generation, path, image = emitted[0]
    assert generation == 1
    assert path == str(broken)
    # 破損していても None ではなく isNull() な QImage を返し、受信側で失敗表示に回す
    assert image.isNull()
    # 失敗理由をログに残している（未対応フォーマット/破損等の切り分け用）
    assert any("failed to load image" in record.message for record in caplog.records)


def test_load_image_emits_null_image_for_missing_file(tmp_path) -> None:
    loader = ImageLoader()
    emitted = _collect_load_image(loader)

    loader.load_image(2, str(tmp_path / "does_not_exist.png"))

    assert len(emitted) == 1
    assert emitted[0][2].isNull()


def test_load_image_loads_image_larger_than_default_allocation_limit(tmp_path) -> None:
    """デフォルトの 256MB 割り当て上限を超える巨大画像も読み込めること（回帰防止）。

    9000x9000 の RGB32 はデコード後 ≈ 309MB で Qt6 のデフォルト上限を超える。
    setAllocationLimit(0) を入れていないと read() が null を返してしまう。
    """
    big = tmp_path / "huge.png"
    _save_image(big, 9000, 9000)

    loader = ImageLoader()
    emitted = _collect_load_image(loader)

    loader.load_image(3, str(big))

    assert len(emitted) == 1
    image = emitted[0][2]
    assert not image.isNull()
    assert (image.width(), image.height()) == (9000, 9000)
