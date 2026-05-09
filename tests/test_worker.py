import os

from worker import ImageLoader


def test_load_file_list_emits_supported_images_in_sorted_order(tmp_path) -> None:
    image_a = tmp_path / "b.PNG"
    image_b = tmp_path / "a.jpg"
    ignored = tmp_path / "memo.txt"
    image_a.write_bytes(b"fake")
    image_b.write_bytes(b"fake")
    ignored.write_text("not an image", encoding="utf-8")

    emitted: list[tuple[list[str], int]] = []
    loader = ImageLoader()
    loader.list_loaded.connect(lambda paths, index: emitted.append((paths, index)))

    target_path = os.path.normcase(str(image_a))
    loader.load_file_list(str(tmp_path), target_path)

    assert emitted == [
        (
            sorted([os.path.normcase(str(image_a)), os.path.normcase(str(image_b))]),
            1,
        )
    ]


def test_load_file_list_emits_empty_result_for_missing_directory(tmp_path) -> None:
    emitted: list[tuple[list[str], int]] = []
    loader = ImageLoader()
    loader.list_loaded.connect(lambda paths, index: emitted.append((paths, index)))

    loader.load_file_list(str(tmp_path / "missing"), "missing.png")

    assert emitted == [([], -1)]
