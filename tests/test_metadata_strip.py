import io
import os

import pytest
from PIL import ExifTags, Image, ImageCms, PngImagePlugin

from hiyoko_viewer.core.metadata_strip import (
    UnsupportedFormatError,
    can_strip_metadata,
    strip_metadata,
    strip_metadata_bytes,
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


def _gradient(mode: str = "RGB") -> Image.Image:
    image = Image.new(mode, (32, 24))
    image.putdata([((x * 8) % 256, (y * 10) % 256, 128) for y in range(24) for x in range(32)])
    return image


def _pixels(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").tobytes()


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
    assert _pixels(stripped) == _pixels(original)
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
    assert _pixels(stripped) == _pixels(original)
    with Image.open(io.BytesIO(stripped)) as image:
        assert "parameters" not in image.info
        assert "Comment" not in image.info
        assert image.info.get("icc_profile") == _icc()
        assert dict(image.getexif()) == {0x0112: 8}


def test_strip_webp_removes_exif_and_xmp_and_updates_flags() -> None:
    buffer = io.BytesIO()
    _gradient().save(buffer, "WEBP", lossless=True, exif=_photo_exif(), xmp=XMP, icc_profile=_icc())
    original = buffer.getvalue()

    stripped = strip_metadata_bytes(original)

    assert b"GCamera" not in stripped
    assert b"SERIAL123" not in stripped
    assert b"XMP " not in stripped
    assert _pixels(stripped) == _pixels(original)
    # VP8X の XMP フラグが落ち、Orientation がないので EXIF フラグも落ちる
    vp8x_flags = stripped[stripped.index(b"VP8X") + 8]
    assert vp8x_flags & 0x0C == 0
    with Image.open(io.BytesIO(stripped)) as image:
        assert not image.getexif()
        assert image.info.get("icc_profile") == _icc()


def test_strip_metadata_overwrites_file_and_keeps_mtime(tmp_path) -> None:
    path = tmp_path / "photo.jpg"
    path.write_bytes(_jpeg())
    os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))

    assert strip_metadata(str(path)) is True

    assert b"secret comment" not in path.read_bytes()
    assert path.stat().st_mtime_ns == 1_700_000_000_000_000_000
    assert [p.name for p in tmp_path.iterdir()] == ["photo.jpg"]


def test_strip_metadata_returns_false_when_nothing_to_remove(tmp_path) -> None:
    path = tmp_path / "plain.png"
    _gradient().save(path)
    before = path.read_bytes()

    assert strip_metadata(str(path)) is False
    assert path.read_bytes() == before


def test_unsupported_format_is_rejected(tmp_path) -> None:
    path = tmp_path / "anim.gif"
    _gradient().save(path)

    assert can_strip_metadata(str(path)) is False
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
