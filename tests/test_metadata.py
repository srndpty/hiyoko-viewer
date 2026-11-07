from types import SimpleNamespace

from PIL import ExifTags, Image, ImageCms

from hiyoko_viewer.core import metadata
from hiyoko_viewer.core.metadata import extract_metadata_text, load_metadata_text
from hiyoko_viewer.ui import main_window
from hiyoko_viewer.ui.main_window import ImageViewer


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
    # UNICODE 指定子(8バイト)＋ UTF-16-LE 本体という実際の EXIF UserComment の形式
    user_comment = b"UNICODE\x00" + "AI prompt".encode("utf-16-le")
    text = extract_metadata_text(_FakeImage(exif={37510: user_comment, 270: long_value}))

    assert "--- AI生成パラメータ (UserComment) ---" in text
    assert "AI prompt" in text
    assert "--- Exif 基本情報 ---" in text
    assert f"ImageDescription: {'x' * 100}..." in text


def test_extract_metadata_text_skips_non_bytes_user_comment() -> None:
    text = extract_metadata_text(_FakeImage(exif={37510: "not bytes"}))

    assert "--- AI生成パラメータ (UserComment) ---" not in text
    assert "UserComment: not bytes" in text


def _save_photo_with_metadata(path) -> None:
    exif = Image.Exif()
    exif[0x010F] = "Google"  # Make
    exif[0x0110] = "Pixel 7a"  # Model
    exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
    exif_ifd[0x829A] = (1, 120)  # ExposureTime
    exif_ifd[0x829D] = (19, 10)  # FNumber
    exif_ifd[0x8827] = 400  # ISOSpeedRatings
    exif_ifd[0x9003] = "2026:11:07 21:04:33"  # DateTimeOriginal
    exif_ifd[0x9286] = b"UNICODE\x00" + "photo note".encode("utf-16-le")  # UserComment
    exif_ifd[0x927C] = b"\x01\x02\x03\xff"  # MakerNote
    gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps_ifd[1] = "N"
    gps_ifd[2] = (35.0, 41.0, 24.0)
    gps_ifd[3] = "W"
    gps_ifd[4] = (139.0, 30.0, 0.0)
    xmp = (
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<rdf:Description xmlns:GCamera="http://ns.google.com/photos/1.0/camera/"'
        b' xmlns:dc="http://purl.org/dc/elements/1.1/" GCamera:MotionPhoto="1">'
        b"<dc:subject><rdf:Bag><rdf:li>bird</rdf:li></rdf:Bag></dc:subject>"
        b"</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (4, 4)).save(
        path, "JPEG", exif=exif, xmp=xmp, icc_profile=icc, comment=b"jpeg comment"
    )


def test_load_metadata_text_expands_exif_gps_and_other_metadata(tmp_path) -> None:
    image_path = tmp_path / "photo.jpg"
    _save_photo_with_metadata(image_path)

    text = load_metadata_text(str(image_path))

    # IFD0 のポインタ値は出さず、サブ IFD を展開する
    assert "ExifOffset" not in text
    assert "GPSInfo:" not in text
    assert "--- Exif 基本情報 ---" in text
    assert "Model: Pixel 7a" in text
    assert "--- Exif 撮影情報 ---" in text
    assert "ExposureTime: 1/120 秒" in text
    assert "FNumber: f/1.9" in text
    assert "ISOSpeedRatings: 400" in text
    assert "DateTimeOriginal: 2026:11:07 21:04:33" in text
    assert "--- AI生成パラメータ (UserComment) ---" in text
    assert "UserComment: photo note" in text
    assert "MakerNote: <バイナリ 4 bytes>" in text
    assert "--- GPS 位置情報 ---" in text
    assert "緯度経度: 35.690000, -139.500000" in text
    assert "--- JPEG コメント ---" in text
    assert "jpeg comment" in text
    assert "--- XMP ---" in text
    assert "GCamera:MotionPhoto: 1" in text
    assert "dc:subject: bird" in text
    assert "--- ICC カラープロファイル ---" in text
    assert "プロファイル: sRGB" in text


def test_extract_metadata_text_falls_back_to_raw_xmp_when_invalid() -> None:
    text = extract_metadata_text(_FakeImage(info={"xmp": b"<broken"}))

    assert "--- XMP ---" in text
    assert "<broken" in text


def test_extract_metadata_text_returns_no_metadata_message() -> None:
    assert extract_metadata_text(_FakeImage()) == metadata.NO_METADATA_TEXT


def test_load_metadata_text_reads_image_without_metadata(tmp_path) -> None:
    image_path = tmp_path / "plain.png"
    Image.new("RGB", (1, 1)).save(image_path)

    assert load_metadata_text(str(image_path)) == metadata.NO_METADATA_TEXT


def test_load_metadata_text_reports_open_errors(tmp_path) -> None:
    text = load_metadata_text(str(tmp_path / "missing.png"))

    assert text.startswith("メタデータの読み込み中にエラーが発生しました:")


def test_show_metadata_dialog_passes_loaded_metadata_to_dialog(monkeypatch) -> None:
    dialogs: list[dict] = []
    viewer = SimpleNamespace(image_files=[r"C:\images\a.png"], current_index=0)
    monkeypatch.setattr(
        main_window, "load_metadata_text", lambda file_path: f"metadata:{file_path}"
    )

    class _Dialog:
        def __init__(self, title: str, content: str, parent, **kwargs) -> None:
            dialogs.append({"title": title, "content": content, "parent": parent})

        def exec(self) -> None:
            dialogs[-1]["executed"] = True

    monkeypatch.setattr(main_window, "MetadataDialog", _Dialog)

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
        main_window,
        "MetadataDialog",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not show dialog")),
    )

    ImageViewer.show_metadata_dialog(viewer)


class _FakeStripDialog:
    def __init__(self) -> None:
        self.busy_history: list[bool] = []
        self.content: str | None = None

    def set_busy(self, busy: bool) -> None:
        self.busy_history.append(busy)

    def set_content(self, content: str) -> None:
        self.content = content


def _strip_viewer(file_path: str) -> SimpleNamespace:
    events: list[str] = []
    viewer = SimpleNamespace(
        image_files=[file_path],
        current_index=0,
        events=events,
        _metadata_strip_task=None,
        _metadata_strip_dialog=None,
        _release_current_file_handles=lambda: events.append("release"),
        load_image_by_index=lambda: events.append("reload"),
        statusBar=lambda: SimpleNamespace(
            showMessage=lambda msg, ms=0: events.append(msg),
            clearMessage=lambda: events.append("clear"),
        ),
    )
    viewer._reload_if_current = lambda path: ImageViewer._reload_if_current(viewer, path)

    def start_task(path: str) -> SimpleNamespace:
        events.append(f"start:{path}")
        return SimpleNamespace(file_path=path)

    viewer._start_metadata_strip_task = start_task
    return viewer


def _answer(monkeypatch, button) -> None:
    monkeypatch.setattr(main_window.QMessageBox, "question", lambda *a: button)


def test_strip_metadata_with_confirmation_does_nothing_when_cancelled(monkeypatch) -> None:
    viewer = _strip_viewer(r"C:\images\a.jpg")
    dialog = _FakeStripDialog()
    _answer(monkeypatch, main_window.QMessageBox.StandardButton.No)

    ImageViewer._strip_metadata_with_confirmation(viewer, r"C:\images\a.jpg", dialog)

    assert viewer.events == []
    assert dialog.busy_history == []
    assert viewer._metadata_strip_task is None


def test_strip_metadata_with_confirmation_starts_background_task(monkeypatch) -> None:
    viewer = _strip_viewer(r"C:\images\a.jpg")
    dialog = _FakeStripDialog()
    _answer(monkeypatch, main_window.QMessageBox.StandardButton.Yes)

    ImageViewer._strip_metadata_with_confirmation(viewer, r"C:\images\a.jpg", dialog)

    assert viewer.events[0] == "release"
    assert viewer.events[-1] == r"start:C:\images\a.jpg"
    assert dialog.busy_history == [True]
    assert viewer._metadata_strip_task.file_path == r"C:\images\a.jpg"
    assert any("メタデータを削除中" in e for e in viewer.events)
    assert viewer._metadata_strip_dialog is dialog


def test_strip_metadata_with_confirmation_ignores_request_while_running(monkeypatch) -> None:
    viewer = _strip_viewer(r"C:\images\a.jpg")
    viewer._metadata_strip_task = SimpleNamespace(file_path=r"C:\images\a.jpg")
    monkeypatch.setattr(
        main_window.QMessageBox,
        "question",
        lambda *a: (_ for _ in ()).throw(AssertionError("should not ask")),
    )

    ImageViewer._strip_metadata_with_confirmation(viewer, r"C:\images\a.jpg", _FakeStripDialog())

    assert viewer.events == []


def _completed_viewer(file_path: str) -> tuple[SimpleNamespace, _FakeStripDialog]:
    viewer = _strip_viewer(file_path)
    dialog = _FakeStripDialog()
    viewer._metadata_strip_task = SimpleNamespace(file_path=file_path)
    viewer._metadata_strip_dialog = dialog
    return viewer, dialog


def test_on_metadata_strip_completed_updates_dialog_and_reloads(monkeypatch) -> None:
    viewer, dialog = _completed_viewer(r"C:\images\a.jpg")
    monkeypatch.setattr(main_window, "load_metadata_text", lambda path: f"after:{path}")

    ImageViewer._on_metadata_strip_completed(viewer, True, None)

    assert dialog.busy_history == [False]
    assert dialog.content == r"after:C:\images\a.jpg"
    assert "reload" in viewer.events
    assert "メタデータを削除しました: a.jpg" in viewer.events
    # スレッドの参照は finished まで保持する（completed の時点ではまだ終了していないことがある）
    assert viewer._metadata_strip_task is not None
    assert viewer._metadata_strip_dialog is None


def test_on_metadata_strip_completed_warns_when_backup_remains(monkeypatch) -> None:
    from hiyoko_viewer.core.metadata_strip import BackupCleanupError

    viewer, dialog = _completed_viewer(r"C:\images\a.jpg")
    warnings: list[str] = []
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda parent, t, m: warnings.append(m))
    monkeypatch.setattr(main_window, "load_metadata_text", lambda path: "after")
    error = BackupCleanupError(r"C:\images\.hiyoko-strip-x.bak", PermissionError("locked"))

    ImageViewer._on_metadata_strip_completed(viewer, True, error)

    assert dialog.content == "after"
    assert warnings and r"C:\images\.hiyoko-strip-x.bak" in warnings[0]


def test_on_metadata_strip_finished_releases_task() -> None:
    viewer, _dialog = _completed_viewer(r"C:\images\a.jpg")
    deleted: list[str] = []
    viewer._metadata_strip_task.deleteLater = lambda: deleted.append("deleted")

    ImageViewer._on_metadata_strip_finished(viewer)

    assert viewer._metadata_strip_task is None
    assert deleted == ["deleted"]


def test_quit_is_deferred_until_metadata_strip_finishes(monkeypatch) -> None:
    viewer, _dialog = _completed_viewer(r"C:\images\a.jpg")
    viewer._metadata_strip_task.deleteLater = lambda: None
    quits: list[str] = []
    monkeypatch.setattr(
        main_window.QApplication,
        "instance",
        lambda: SimpleNamespace(quit=lambda: quits.append("quit")),
    )
    viewer._quit_application = lambda: ImageViewer._quit_application(viewer)

    ImageViewer._quit_application(viewer)
    assert quits == []
    assert viewer._quit_after_metadata_strip is True

    ImageViewer._on_metadata_strip_finished(viewer)
    assert quits == ["quit"]
    assert viewer._quit_after_metadata_strip is False


def test_on_metadata_strip_completed_reports_nothing_to_remove() -> None:
    viewer, dialog = _completed_viewer(r"C:\images\a.jpg")

    ImageViewer._on_metadata_strip_completed(viewer, False, None)

    assert dialog.content is None
    assert "削除するメタデータはありませんでした" in viewer.events


def test_on_metadata_strip_completed_reports_failure(monkeypatch) -> None:
    viewer, dialog = _completed_viewer(r"C:\images\a.jpg")
    warnings: list[str] = []
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda parent, t, m: warnings.append(m))

    ImageViewer._on_metadata_strip_completed(viewer, False, PermissionError("locked"))

    assert warnings and "locked" in warnings[0]
    assert dialog.busy_history == [False]
    assert dialog.content is None
    assert "reload" in viewer.events


def test_metadata_strip_task_runs_in_background(tmp_path) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from hiyoko_viewer.ui.metadata_strip_task import MetadataStripTask

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "a.png"
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "secret")
    Image.new("RGB", (2, 2)).save(path, pnginfo=info)

    results: list[tuple] = []
    task = MetadataStripTask(str(path))
    task.completed.connect(lambda changed, error: results.append((changed, error)))
    task.start()
    assert task.wait(10000)
    app.processEvents()

    assert results == [(True, None)]
    assert b"secret" not in path.read_bytes()


def test_metadata_strip_task_reports_backup_cleanup_as_changed(monkeypatch) -> None:
    from hiyoko_viewer.core.metadata_strip import BackupCleanupError
    from hiyoko_viewer.ui import metadata_strip_task

    error = BackupCleanupError("backup.bak", PermissionError("locked"))
    monkeypatch.setattr(
        metadata_strip_task, "strip_metadata", lambda path: (_ for _ in ()).throw(error)
    )
    results: list[tuple] = []
    task = metadata_strip_task.MetadataStripTask("a.jpg")
    task.completed.connect(lambda changed, err: results.append((changed, err)))

    task.run()

    assert results == [(True, error)]
