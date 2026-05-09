from types import SimpleNamespace

from PIL import Image

import image_viewer
from image_viewer import ImageViewer, extract_metadata_text, load_metadata_text


class _FakeImage:
    def __init__(self, info: dict | None = None, exif: dict | None = None) -> None:
        self.info = info or {}
        self._exif = exif or {}

    def getexif(self) -> dict:
        return self._exif


def test_extract_metadata_text_formats_novelai_json() -> None:
    text = extract_metadata_text(_FakeImage(info={"Comment": '{"prompt":"bird","steps":20}'}))

    assert "--- NovelAI パラメータ (JSON) ---" in text
    assert '"prompt": "bird"' in text
    assert '"steps": 20' in text


def test_extract_metadata_text_uses_raw_comment_when_json_is_invalid() -> None:
    text = extract_metadata_text(_FakeImage(info={"Comment": "raw prompt"}))

    assert "--- NovelAI パラメータ (Comment) ---" in text
    assert "raw prompt" in text


def test_extract_metadata_text_includes_parameters_and_description() -> None:
    text = extract_metadata_text(
        _FakeImage(info={"parameters": "positive prompt", "Description": "plain description"})
    )

    assert "--- AI生成パラメータ (PNG) ---" in text
    assert "positive prompt" in text
    assert "--- AI生成パラメータ (Description) ---" in text
    assert "plain description" in text


def test_extract_metadata_text_ignores_description_when_comment_exists() -> None:
    text = extract_metadata_text(
        _FakeImage(info={"Comment": "raw prompt", "Description": "ignored"})
    )

    assert "raw prompt" in text
    assert "ignored" not in text


def test_extract_metadata_text_includes_exif_user_comment_and_truncates_long_values() -> None:
    long_value = "x" * 120
    text = extract_metadata_text(
        _FakeImage(exif={37510: b"UNICODE\x00\x00AI prompt", 270: long_value})
    )

    assert "--- AI生成パラメータ (UserComment) ---" in text
    assert "AI prompt" in text
    assert "--- Exif 詳細 ---" in text
    assert f"ImageDescription: {'x' * 100}..." in text


def test_extract_metadata_text_skips_non_bytes_user_comment() -> None:
    text = extract_metadata_text(_FakeImage(exif={37510: "not bytes"}))

    assert "--- AI生成パラメータ (UserComment) ---" not in text
    assert "UserComment: not bytes" in text


def test_extract_metadata_text_returns_no_metadata_message() -> None:
    assert extract_metadata_text(_FakeImage()) == image_viewer.NO_METADATA_TEXT


def test_load_metadata_text_reads_image_without_metadata(tmp_path) -> None:
    image_path = tmp_path / "plain.png"
    Image.new("RGB", (1, 1)).save(image_path)

    assert load_metadata_text(str(image_path)) == image_viewer.NO_METADATA_TEXT


def test_load_metadata_text_reports_open_errors(tmp_path) -> None:
    text = load_metadata_text(str(tmp_path / "missing.png"))

    assert text.startswith("メタデータの読み込み中にエラーが発生しました:")


def test_show_metadata_dialog_passes_loaded_metadata_to_dialog(monkeypatch) -> None:
    dialogs: list[dict] = []
    viewer = SimpleNamespace(image_files=[r"C:\images\a.png"], current_index=0)
    monkeypatch.setattr(
        image_viewer, "load_metadata_text", lambda file_path: f"metadata:{file_path}"
    )

    class _Dialog:
        def __init__(self, title: str, content: str, parent) -> None:
            dialogs.append({"title": title, "content": content, "parent": parent})

        def exec(self) -> None:
            dialogs[-1]["executed"] = True

    monkeypatch.setattr(image_viewer, "MetadataDialog", _Dialog)

    ImageViewer.show_metadata_dialog(viewer)

    assert dialogs == [
        {
            "title": "メタデータ: a.png",
            "content": r"metadata:C:\images\a.png",
            "parent": viewer,
            "executed": True,
        }
    ]


def test_show_metadata_dialog_returns_without_images(monkeypatch) -> None:
    viewer = SimpleNamespace(image_files=[])
    monkeypatch.setattr(
        image_viewer,
        "MetadataDialog",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not show dialog")),
    )

    ImageViewer.show_metadata_dialog(viewer)
