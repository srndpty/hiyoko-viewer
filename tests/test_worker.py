import os

from worker import ImageLoader


def test_load_file_list_emits_supported_images_in_sorted_order(tmp_path) -> None:
    image_a = tmp_path / "b.PNG"
    image_b = tmp_path / "a.jpg"
    ignored = tmp_path / "memo.txt"
    image_a.write_bytes(b"fake")
    image_b.write_bytes(b"fake")
    ignored.write_text("not an image", encoding="utf-8")

    emitted: list[tuple[int, list[str], int]] = []
    loader = ImageLoader()
    loader.list_loaded.connect(lambda gen, paths, index: emitted.append((gen, paths, index)))

    target_path = os.path.normcase(str(image_a))
    loader.load_file_list(1, str(tmp_path), target_path)

    assert emitted == [
        (
            1,
            sorted([os.path.normcase(str(image_a)), os.path.normcase(str(image_b))]),
            1,
        )
    ]


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

    loader.load_file_list(3, str(tmp_path), os.path.normcase(str(tmp_path / "missing.png")))

    assert emitted == [
        (
            3,
            sorted([os.path.normcase(str(image_a)), os.path.normcase(str(image_b))]),
            0,
        )
    ]
