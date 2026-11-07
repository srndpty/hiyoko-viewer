import io
import os
import struct
import zlib

import pytest
from PIL import ExifTags, Image, ImageCms, ImageSequence, PngImagePlugin

from hiyoko_viewer.core import metadata_strip
from hiyoko_viewer.core.metadata_strip import (
    UnsupportedFormatError,
    can_strip_metadata,
    strip_metadata,
    strip_metadata_bytes,
    strip_unsupported_reason,
)

XMP = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description xmlns:GCamera="http://ns.google.com/photos/1.0/camera/"'
    b' GCamera:MotionPhoto="1"/></rdf:RDF></x:xmpmeta>'
)


def _icc() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _photo_exif(orientation: int | None = None) -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "Google"  # Make
    exif[0x013B] = "Someone"  # Artist
    if orientation is not None:
        exif[0x0112] = orientation
    exif.get_ifd(ExifTags.IFD.Exif)[0xA431] = "SERIAL123"  # BodySerialNumber
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[1] = "N"
    gps[2] = (35.0, 41.0, 24.0)
    return exif


def _gradient(mode: str = "RGB", shift: int = 0) -> Image.Image:
    image = Image.new("RGB", (32, 24))
    image.putdata(
        [((x * 8 + shift) % 256, (y * 10) % 256, 128) for y in range(24) for x in range(32)]
    )
    return image.convert(mode)


def _frames(data: bytes) -> list[bytes]:
    with Image.open(io.BytesIO(data)) as image:
        return [frame.convert("RGBA").tobytes() for frame in ImageSequence.Iterator(image)]


def _jpeg(*, orientation: int | None = 6, progressive: bool = False, trailer: bytes = b"") -> bytes:
    buffer = io.BytesIO()
    _gradient().save(
        buffer,
        "JPEG",
        exif=_photo_exif(orientation),
        xmp=XMP,
        icc_profile=_icc(),
        comment=b"secret comment",
        progressive=progressive,
    )
    return buffer.getvalue() + trailer


def _jpeg_insert_after_soi(data: bytes, marker: int, payload: bytes) -> bytes:
    segment = bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload
    return data[:2] + segment + data[2:]


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def _png_insert_after_ihdr(data: bytes, chunk: bytes) -> bytes:
    ihdr_end = 8 + 8 + 13 + 4
    return data[:ihdr_end] + chunk + data[ihdr_end:]


def _webp_append_chunk(data: bytes, fourcc: bytes, payload: bytes) -> bytes:
    pad = b"\x00" if len(payload) % 2 else b""
    body = data[8:] + fourcc + struct.pack("<I", len(payload)) + payload + pad
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _plain_png() -> bytes:
    buffer = io.BytesIO()
    _gradient().save(buffer, "PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------
# JPEG
# --------------------------------------------------------------------------
@pytest.mark.parametrize("progressive", [False, True])
def test_strip_jpeg_removes_metadata_and_keeps_pixels(progressive: bool) -> None:
    original = _jpeg(progressive=progressive, trailer=b"MOTION-PHOTO-VIDEO" * 10)

    stripped = strip_metadata_bytes(original)

    assert b"MOTION-PHOTO-VIDEO" not in stripped
    assert stripped.endswith(b"\xff\xd9")
    assert b"secret comment" not in stripped
    assert b"GCamera" not in stripped
    assert b"SERIAL123" not in stripped
    assert b"Someone" not in stripped
    assert _frames(stripped) == _frames(original)
    with Image.open(io.BytesIO(stripped)) as image:
        assert dict(image.getexif()) == {0x0112: 6}
        assert image.info.get("icc_profile") == _icc()
        assert "xmp" not in image.info
        assert "comment" not in image.info


def test_strip_jpeg_without_orientation_drops_exif_entirely() -> None:
    stripped = strip_metadata_bytes(_jpeg(orientation=None))

    with Image.open(io.BytesIO(stripped)) as image:
        assert not image.getexif()
        assert "exif" not in image.info


def test_strip_jpeg_is_idempotent() -> None:
    stripped = strip_metadata_bytes(_jpeg())

    assert strip_metadata_bytes(stripped) == stripped


def test_strip_jpeg_removes_jfxx_thumbnail_with_exif() -> None:
    thumbnail_exif = Image.Exif()
    thumbnail_exif[0x010E] = "THUMB-SECRET"  # ImageDescription
    thumbnail = io.BytesIO()
    Image.new("RGB", (4, 4)).save(thumbnail, "JPEG", exif=thumbnail_exif)
    original = _jpeg_insert_after_soi(_jpeg(), 0xE0, b"JFXX\x00\x10" + thumbnail.getvalue())

    stripped = strip_metadata_bytes(original)

    assert b"THUMB-SECRET" not in stripped
    assert b"JFXX" not in stripped
    assert _frames(stripped) == _frames(original)


def test_strip_jpeg_removes_jfif_embedded_thumbnail() -> None:
    # JFIF 1.01, 単位なし, 密度 1x1, サムネイル 1x4 (RGB 12 バイト)
    jfif = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x01\x04" + b"THUMBPIXELS!"
    original = _jpeg_insert_after_soi(_jpeg(), 0xE0, jfif)

    stripped = strip_metadata_bytes(original)

    assert b"THUMBPIXELS!" not in stripped
    assert stripped.count(b"JFIF\x00") == 1
    assert _frames(stripped) == _frames(original)


def test_strip_jpeg_removes_unknown_app_segments() -> None:
    original = _jpeg_insert_after_soi(_jpeg(), 0xE9, b"VENDOR-PRIVATE-DATA")

    assert b"VENDOR-PRIVATE-DATA" not in strip_metadata_bytes(original)


def test_strip_ultra_hdr_like_mpo_keeps_only_primary_image() -> None:
    buffer = io.BytesIO()
    _gradient().save(
        buffer,
        "MPO",
        save_all=True,
        append_images=[_gradient(shift=50)],
        exif=_photo_exif(),
        xmp=XMP,
    )
    original = buffer.getvalue()

    stripped = strip_metadata_bytes(original)

    assert b"MPF\x00" not in stripped
    with Image.open(io.BytesIO(stripped)) as image:
        assert getattr(image, "n_frames", 1) == 1
    assert _frames(stripped) == _frames(original)[:1]


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------
def test_strip_png_removes_text_and_exif_and_keeps_icc() -> None:
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("parameters", "secret prompt")
    pnginfo.add_itxt("Comment", "secret itxt")
    buffer = io.BytesIO()
    _gradient().save(
        buffer, "PNG", pnginfo=pnginfo, exif=_photo_exif(orientation=8), icc_profile=_icc()
    )
    original = buffer.getvalue()

    stripped = strip_metadata_bytes(original)

    assert b"secret" not in stripped
    assert b"SERIAL123" not in stripped
    assert _frames(stripped) == _frames(original)
    with Image.open(io.BytesIO(stripped)) as image:
        assert "parameters" not in image.info
        assert "Comment" not in image.info
        assert image.info.get("icc_profile") == _icc()
        assert dict(image.getexif()) == {0x0112: 8}


def test_strip_png_removes_unknown_private_chunk(tmp_path) -> None:
    path = tmp_path / "private.png"
    path.write_bytes(_png_insert_after_ihdr(_plain_png(), _png_chunk(b"meTa", b"PRIVATE-DATA")))

    assert strip_metadata(str(path)) is True
    assert b"PRIVATE-DATA" not in path.read_bytes()


def test_strip_png_rejects_unknown_critical_chunk() -> None:
    original = _png_insert_after_ihdr(_plain_png(), _png_chunk(b"MeTa", b"data"))

    with pytest.raises(ValueError, match="MeTa"):
        strip_metadata_bytes(original)


def test_strip_png_replaces_iccp_profile_name() -> None:
    iccp = _png_chunk(b"iCCP", b"Secret Owner\x00\x00" + zlib.compress(_icc()))
    original = _png_insert_after_ihdr(_plain_png(), iccp)

    stripped = strip_metadata_bytes(original)

    assert b"Secret Owner" not in stripped
    with Image.open(io.BytesIO(stripped)) as image:
        assert image.info.get("icc_profile") == _icc()


def test_strip_apng_keeps_all_frames(tmp_path) -> None:
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("parameters", "secret prompt")
    path = tmp_path / "anim.png"
    frames = [_gradient("RGBA", shift) for shift in (0, 60, 120)]
    frames[0].save(path, save_all=True, append_images=frames[1:], pnginfo=pnginfo, duration=50)
    original = path.read_bytes()

    assert strip_metadata(str(path)) is True

    stripped = path.read_bytes()
    assert b"secret prompt" not in stripped
    assert len(_frames(stripped)) == 3
    assert _frames(stripped) == _frames(original)


# --------------------------------------------------------------------------
# WebP
# --------------------------------------------------------------------------
def test_strip_webp_removes_exif_xmp_and_c2pa() -> None:
    buffer = io.BytesIO()
    _gradient().save(buffer, "WEBP", lossless=True, exif=_photo_exif(), xmp=XMP, icc_profile=_icc())
    original = _webp_append_chunk(buffer.getvalue(), b"C2PA", b"C2PA-MANIFEST-DATA")
    original = _webp_append_chunk(original, b"priv", b"PRIVATE-DATA")

    stripped = strip_metadata_bytes(original)

    assert b"GCamera" not in stripped
    assert b"SERIAL123" not in stripped
    assert b"C2PA-MANIFEST-DATA" not in stripped
    assert b"PRIVATE-DATA" not in stripped
    assert _frames(stripped) == _frames(original)
    # VP8X の XMP フラグが落ち、Orientation がないので EXIF フラグも落ちる
    vp8x_flags = stripped[stripped.index(b"VP8X") + 8]
    assert vp8x_flags & 0x0C == 0
    with Image.open(io.BytesIO(stripped)) as image:
        assert not image.getexif()
        assert image.info.get("icc_profile") == _icc()


def test_strip_animated_webp_keeps_all_frames(tmp_path) -> None:
    path = tmp_path / "anim.webp"
    frames = [_gradient("RGBA", shift) for shift in (0, 60, 120)]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        lossless=True,
        duration=50,
        exif=_photo_exif(),
        xmp=XMP,
    )
    original = path.read_bytes()

    assert strip_metadata(str(path)) is True

    stripped = path.read_bytes()
    assert b"SERIAL123" not in stripped
    assert b"GCamera" not in stripped
    assert len(_frames(stripped)) == 3
    assert _frames(stripped) == _frames(original)


# --------------------------------------------------------------------------
# ファイル操作
# --------------------------------------------------------------------------
def test_strip_metadata_overwrites_file_and_keeps_mtime(tmp_path) -> None:
    path = tmp_path / "photo.jpg"
    path.write_bytes(_jpeg())
    os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))

    assert strip_metadata(str(path)) is True

    assert b"secret comment" not in path.read_bytes()
    assert path.stat().st_mtime_ns == 1_700_000_000_000_000_000
    assert [p.name for p in tmp_path.iterdir()] == ["photo.jpg"]


@pytest.mark.skipif(os.name != "nt", reason="代替データストリームは NTFS のみ")
def test_strip_metadata_keeps_alternate_data_stream(tmp_path) -> None:
    path = tmp_path / "photo.jpg"
    path.write_bytes(_jpeg())
    try:
        with open(f"{path}:extra", "wb") as f:
            f.write(b"stream data")
    except OSError:
        pytest.skip("代替データストリームを作れないファイルシステム")

    assert strip_metadata(str(path)) is True

    with open(f"{path}:extra", "rb") as f:
        assert f.read() == b"stream data"
    assert b"secret comment" not in path.read_bytes()


def test_strip_metadata_rejects_symlink(tmp_path) -> None:
    real = tmp_path / "real.jpg"
    real.write_bytes(_jpeg())
    alias = tmp_path / "alias.jpg"
    try:
        os.symlink(real, alias)
    except (OSError, NotImplementedError):
        pytest.skip("シンボリックリンクを作成できない環境")
    before = real.read_bytes()

    assert strip_unsupported_reason(str(alias))
    with pytest.raises(UnsupportedFormatError):
        strip_metadata(str(alias))
    assert alias.is_symlink()
    assert real.read_bytes() == before


def test_strip_metadata_rejects_hard_link(tmp_path) -> None:
    real = tmp_path / "real.jpg"
    real.write_bytes(_jpeg())
    other = tmp_path / "other.jpg"
    try:
        os.link(real, other)
    except OSError:
        pytest.skip("ハードリンクを作成できない環境")

    assert strip_unsupported_reason(str(real))
    with pytest.raises(UnsupportedFormatError):
        strip_metadata(str(real))
    assert b"secret comment" in other.read_bytes()


def test_strip_metadata_returns_false_when_nothing_to_remove(tmp_path) -> None:
    path = tmp_path / "plain.png"
    path.write_bytes(_plain_png())
    before = path.read_bytes()

    assert strip_metadata(str(path)) is False
    assert path.read_bytes() == before


def test_strip_metadata_refuses_when_pixels_change(tmp_path, monkeypatch) -> None:
    path = tmp_path / "a.png"
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("parameters", "secret prompt")
    _gradient().save(path, pnginfo=pnginfo)
    before = path.read_bytes()
    other = io.BytesIO()
    _gradient(shift=1).save(other, "PNG")
    monkeypatch.setattr(metadata_strip, "_strip_png", lambda data: other.getvalue())

    with pytest.raises(ValueError, match="一致しません"):
        strip_metadata(str(path))
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["a.png"]


def test_unsupported_format_is_rejected(tmp_path) -> None:
    path = tmp_path / "anim.gif"
    _gradient().save(path)

    assert can_strip_metadata(str(path)) is False
    assert "JPEG / PNG / WebP" in strip_unsupported_reason(str(path))
    with pytest.raises(UnsupportedFormatError):
        strip_metadata(str(path))


def test_can_strip_metadata_detects_supported_formats(tmp_path) -> None:
    jpeg = tmp_path / "a.jpg"
    jpeg.write_bytes(_jpeg())

    assert can_strip_metadata(str(jpeg)) is True
    assert can_strip_metadata(str(tmp_path / "missing.jpg")) is False


def test_broken_jpeg_raises_value_error(tmp_path) -> None:
    path = tmp_path / "broken.jpg"
    path.write_bytes(_jpeg()[:200])
    before = path.read_bytes()

    with pytest.raises(ValueError):
        strip_metadata(str(path))
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "reparse_tag_name", ["IO_REPARSE_TAG_SYMLINK", "IO_REPARSE_TAG_MOUNT_POINT"]
)
def test_strip_metadata_rejects_link_reparse_points(
    tmp_path, monkeypatch, reparse_tag_name
) -> None:
    import stat
    from types import SimpleNamespace

    tag = getattr(stat, reparse_tag_name, None)
    if tag is None:
        pytest.skip("この OS にはリパースタグがない")
    path = tmp_path / "a.jpg"
    path.write_bytes(_jpeg())
    before = path.read_bytes()
    monkeypatch.setattr(
        metadata_strip.os,
        "lstat",
        lambda p: SimpleNamespace(st_mode=stat.S_IFREG, st_reparse_tag=tag, st_nlink=1),
    )

    assert "リンク" in strip_unsupported_reason(str(path))
    with pytest.raises(UnsupportedFormatError):
        strip_metadata(str(path))
    assert path.read_bytes() == before


def test_strip_metadata_allows_cloud_file_reparse_points(tmp_path, monkeypatch) -> None:
    import stat
    from types import SimpleNamespace

    path = tmp_path / "a.jpg"
    path.write_bytes(_jpeg())
    real_lstat = os.lstat
    # OneDrive のクラウドファイル (IO_REPARSE_TAG_CLOUD_6) は許可する
    monkeypatch.setattr(
        metadata_strip.os,
        "lstat",
        lambda p: SimpleNamespace(st_mode=stat.S_IFREG, st_reparse_tag=0x9000601A, st_nlink=1)
        if os.fspath(p) == str(path)
        else real_lstat(p),
    )

    assert strip_unsupported_reason(str(path)) is None


# --------------------------------------------------------------------------
# 表示に関わる情報の検証
# --------------------------------------------------------------------------
def test_strip_animation_keeps_durations_and_loop(tmp_path) -> None:
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("parameters", "secret prompt")
    path = tmp_path / "anim.png"
    frames = [_gradient("RGBA", shift) for shift in (0, 60, 120)]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        pnginfo=pnginfo,
        duration=[40, 80, 120],
        loop=3,
    )

    assert strip_metadata(str(path)) is True

    with Image.open(path) as image:
        assert image.info.get("loop") == 3
        durations = [frame.info.get("duration") for frame in ImageSequence.Iterator(image)]
    assert durations == [40, 80, 120]


def test_strip_metadata_refuses_when_duration_changes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "anim.png"
    frames = [_gradient("RGBA", shift) for shift in (0, 60)]
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("parameters", "secret prompt")
    frames[0].save(path, save_all=True, append_images=frames[1:], pnginfo=pnginfo, duration=50)
    before = path.read_bytes()
    other = io.BytesIO()
    frames[0].save(other, "PNG", save_all=True, append_images=frames[1:], duration=999)
    monkeypatch.setattr(metadata_strip, "_strip_png", lambda data: other.getvalue())

    with pytest.raises(ValueError, match="表示時間"):
        strip_metadata(str(path))
    assert path.read_bytes() == before


def test_strip_metadata_refuses_when_orientation_changes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "a.jpg"
    path.write_bytes(_jpeg(orientation=6))
    before = path.read_bytes()
    monkeypatch.setattr(metadata_strip, "_read_orientation", lambda data: None)

    with pytest.raises(ValueError, match="画像の向き"):
        strip_metadata(str(path))
    assert path.read_bytes() == before


# --------------------------------------------------------------------------
# ReplaceFileW の失敗注入 (Windows の置き換え処理を OS に依存せず検証する)
# --------------------------------------------------------------------------
_real_replace = os.replace


def _setup_replace(monkeypatch, tmp_path, fake) -> tuple:
    path = tmp_path / "photo.jpg"
    path.write_bytes(_jpeg())
    original = path.read_bytes()
    monkeypatch.setattr(metadata_strip, "_USE_REPLACE_FILE", True)
    monkeypatch.setattr(metadata_strip, "_BACKUP_REMOVE_RETRY_DELAYS", ())
    monkeypatch.setattr(metadata_strip, "_win_replace_file", fake)
    return path, original


def _leftovers(tmp_path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir() if p.name != "photo.jpg")


def _fake_success(replaced: str, replacement: str, backup: str) -> int:
    _real_replace(replaced, backup)
    _real_replace(replacement, replaced)
    return 0


def test_replace_success_removes_backup(monkeypatch, tmp_path) -> None:
    path, _original = _setup_replace(monkeypatch, tmp_path, _fake_success)

    assert strip_metadata(str(path)) is True

    assert b"secret comment" not in path.read_bytes()
    assert _leftovers(tmp_path) == []


@pytest.mark.parametrize("error_code", [1175, 1176])
def test_replace_failure_with_original_in_place(monkeypatch, tmp_path, error_code) -> None:
    path, original = _setup_replace(monkeypatch, tmp_path, lambda *a: error_code)

    with pytest.raises(metadata_strip.ReplaceFailedError, match="変更されていません"):
        strip_metadata(str(path))

    assert path.read_bytes() == original
    assert _leftovers(tmp_path) == []


def test_replace_failure_1177_restores_original(monkeypatch, tmp_path) -> None:
    def fake(replaced: str, replacement: str, backup: str) -> int:
        _real_replace(replaced, backup)  # 元ファイルはバックアップ名へ移動済み
        return 1177

    path, original = _setup_replace(monkeypatch, tmp_path, fake)

    with pytest.raises(metadata_strip.ReplaceFailedError, match="元の名前に戻しました"):
        strip_metadata(str(path))

    assert path.read_bytes() == original
    assert _leftovers(tmp_path) == []


def test_replace_failure_1177_keeps_files_when_restore_fails(monkeypatch, tmp_path) -> None:
    def fake(replaced: str, replacement: str, backup: str) -> int:
        _real_replace(replaced, backup)
        return 1177

    path, original = _setup_replace(monkeypatch, tmp_path, fake)

    def failing_replace(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(metadata_strip.os, "replace", failing_replace)

    with pytest.raises(metadata_strip.ReplaceFailedError) as excinfo:
        strip_metadata(str(path))

    monkeypatch.undo()
    leftovers = _leftovers(tmp_path)
    backup = next(name for name in leftovers if name.endswith(".bak"))
    temp = next(name for name in leftovers if name.endswith(".tmp"))
    # 調査・手動復旧のため、元データと削除後データの両方を残し、パスを伝える
    assert (tmp_path / backup).read_bytes() == original
    assert backup in str(excinfo.value)
    assert temp in str(excinfo.value)
    assert not path.exists()


def test_replace_failure_in_unexpected_state_keeps_everything(monkeypatch, tmp_path) -> None:
    def fake(replaced: str, replacement: str, backup: str) -> int:
        with open(replaced, "rb") as src, open(backup, "wb") as dst:
            dst.write(src.read())  # 元ファイルもバックアップも存在する想定外の状態
        return 1177

    path, original = _setup_replace(monkeypatch, tmp_path, fake)

    with pytest.raises(metadata_strip.ReplaceFailedError, match="想定外"):
        strip_metadata(str(path))

    assert path.read_bytes() == original
    assert len(_leftovers(tmp_path)) == 2


def test_backup_cleanup_failure_is_reported(monkeypatch, tmp_path) -> None:
    path, original = _setup_replace(monkeypatch, tmp_path, _fake_success)
    real_remove = os.remove

    def failing_remove(target):
        if str(target).endswith(".bak"):
            raise PermissionError("locked")
        real_remove(target)

    monkeypatch.setattr(metadata_strip.os, "remove", failing_remove)

    with pytest.raises(metadata_strip.BackupCleanupError) as excinfo:
        strip_metadata(str(path))

    assert b"secret comment" not in path.read_bytes()
    backup = tmp_path / os.path.basename(excinfo.value.backup_path)
    assert backup.read_bytes() == original
    assert str(backup) in str(excinfo.value) or backup.name in str(excinfo.value)


def test_lost_update_during_replace_is_rolled_back(monkeypatch, tmp_path) -> None:
    changed = _plain_png()

    def fake(replaced: str, replacement: str, backup: str) -> int:
        with open(replaced, "wb") as f:  # 置き換え直前に別プロセスが書き込んだ想定
            f.write(changed)
        return _fake_success(replaced, replacement, backup)

    path, _original = _setup_replace(monkeypatch, tmp_path, fake)

    with pytest.raises(metadata_strip.FileChangedError):
        strip_metadata(str(path))

    assert path.read_bytes() == changed
    assert _leftovers(tmp_path) == []


def test_change_before_replace_is_detected(monkeypatch, tmp_path) -> None:
    path = tmp_path / "photo.jpg"
    path.write_bytes(_jpeg())
    changed = _plain_png()
    real_verify = metadata_strip._verify_same_image

    def verify_and_modify(original, stripped, fmt):
        real_verify(original, stripped, fmt)
        path.write_bytes(changed)  # 検証中に別プロセスが書き込んだ想定

    monkeypatch.setattr(metadata_strip, "_verify_same_image", verify_and_modify)

    with pytest.raises(metadata_strip.FileChangedError):
        strip_metadata(str(path))

    assert path.read_bytes() == changed
    assert [p.name for p in tmp_path.iterdir()] == ["photo.jpg"]
