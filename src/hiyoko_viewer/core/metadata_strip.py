"""画像ファイルからメタデータを削除して上書き保存する。Qt 非依存。

画像データ自体は再エンコードせず、JPEG のセグメント / PNG のチャンク / WebP の
チャンク単位で取り除くため画質は劣化しない。

残すもの: 画像の向き (Exif Orientation のみを入れ直す)、ICC カラープロファイル、
JFIF / Adobe セグメントなど表示に必要な情報。
消すもの: Exif (GPS・撮影情報・MakerNote 等)、XMP、IPTC、コメント、
PNG のテキストチャンク (AI 生成パラメータ)、C2PA、JPEG 末尾の追加データ
(モーションフォトの動画や HDR ゲインマップ等)。
"""

from __future__ import annotations

import io
import os
import shutil
import struct
import tempfile
import zlib

from PIL import Image

_ORIENTATION_TAG = 0x0112

_JPEG_SOI = b"\xff\xd8"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# PNG で削除するチャンク: テキスト (AI パラメータ含む)・Exif・更新日時・C2PA
_PNG_DROP_CHUNKS = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME", b"caBX"}

# WebP VP8X のフラグ
_WEBP_FLAG_EXIF = 0x08
_WEBP_FLAG_XMP = 0x04


class UnsupportedFormatError(ValueError):
    """メタデータ削除に対応していない形式。"""


def _detect_format(head: bytes) -> str | None:
    if head.startswith(_JPEG_SOI + b"\xff"):
        return "jpeg"
    if head.startswith(_PNG_SIGNATURE):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def can_strip_metadata(file_path: str) -> bool:
    """メタデータ削除に対応した形式 (JPEG / PNG / WebP) かどうか。"""
    try:
        with open(file_path, "rb") as f:
            return _detect_format(f.read(12)) is not None
    except OSError:
        return False


def _read_orientation(data: bytes) -> int | None:
    """回転・反転が必要な Orientation (2〜8) を返す。不要なら None。"""
    try:
        with Image.open(io.BytesIO(data)) as image:
            orientation = image.getexif().get(_ORIENTATION_TAG)
    except Exception:
        return None
    if isinstance(orientation, int) and 2 <= orientation <= 8:
        return orientation
    return None


def _orientation_only_exif(orientation: int) -> bytes:
    """Orientation だけを含む Exif ("Exif\\0\\0" + TIFF) を作る。"""
    exif = Image.Exif()
    exif[_ORIENTATION_TAG] = orientation
    return exif.tobytes()


# --------------------------------------------------------------------------
# JPEG
# --------------------------------------------------------------------------
def _keep_jpeg_segment(marker: int, payload: bytes) -> bool:
    if marker == 0xFE:  # COM
        return False
    if 0xE0 <= marker <= 0xEF:  # APPn
        if marker == 0xE0:  # JFIF / JFXX
            return True
        if marker == 0xE2:  # ICC プロファイルのみ残す (MPF / FlashPix は削除)
            return payload.startswith(b"ICC_PROFILE\x00")
        if marker == 0xEE:  # Adobe (色変換の指定。消すと色が変わり得る)
            return payload.startswith(b"Adobe")
        # APP1 (Exif / XMP)、APP11 (C2PA)、APP13 (IPTC) などは削除
        return False
    return True


def _strip_jpeg(data: bytes) -> bytes:
    out = bytearray(_JPEG_SOI)
    inserted_exif = False
    orientation = _read_orientation(data)
    exif_segment = b""
    if orientation is not None:
        exif_payload = _orientation_only_exif(orientation)
        exif_segment = b"\xff\xe1" + struct.pack(">H", len(exif_payload) + 2) + exif_payload

    pos = 2
    size = len(data)
    try:
        while True:
            if data[pos] != 0xFF:
                raise ValueError("JPEG のマーカーが見つかりません")
            while data[pos] == 0xFF:  # フィルバイトを読み飛ばす
                pos += 1
            marker = data[pos]
            pos += 1

            if marker == 0xD9:  # EOI。これ以降の追加データは捨てる
                out += b"\xff\xd9"
                break
            if 0xD0 <= marker <= 0xD7 or marker == 0x01:  # 長さを持たないマーカー
                out += bytes((0xFF, marker))
                continue

            length = struct.unpack(">H", data[pos : pos + 2])[0]
            if length < 2 or pos + length > size:
                raise ValueError("JPEG のセグメント長が不正です")
            payload = data[pos + 2 : pos + length]
            segment = bytes((0xFF, marker)) + data[pos : pos + length]
            pos += length

            # Exif は APP0 (JFIF) の直後、それ以外のセグメントより前に置く
            if not inserted_exif and marker != 0xE0:
                out += exif_segment
                inserted_exif = True

            if _keep_jpeg_segment(marker, payload):
                out += segment

            if marker == 0xDA:  # SOS: 続くエントロピー符号化データを次のマーカーまでコピー
                start = pos
                while True:
                    i = data.index(b"\xff", pos)
                    following = data[i + 1]
                    if following == 0x00 or 0xD0 <= following <= 0xD7:
                        pos = i + 2  # バイトスタッフィング / リスタートマーカー
                    elif following == 0xFF:
                        pos = i + 1
                    else:
                        break
                out += data[start:i]
                pos = i
    except (IndexError, ValueError, struct.error) as e:
        raise ValueError(f"JPEG の解析に失敗しました: {e}") from e

    return bytes(out)


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------
def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def _strip_png(data: bytes) -> bytes:
    out = bytearray(_PNG_SIGNATURE)
    orientation = _read_orientation(data)
    exif_chunk = b""
    if orientation is not None:
        # PNG の eXIf は "Exif\0\0" ヘッダを含まない生の TIFF
        exif_chunk = _png_chunk(b"eXIf", _orientation_only_exif(orientation)[6:])

    pos = len(_PNG_SIGNATURE)
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("PNG のチャンクが途中で切れています")
        length, chunk_type = struct.unpack(">I4s", data[pos : pos + 8])
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("PNG のチャンクが途中で切れています")
        chunk = data[pos:end]
        pos = end

        # eXIf は最初の画像データより前に置く必要がある
        if exif_chunk and chunk_type in (b"IDAT", b"acTL", b"fcTL"):
            out += exif_chunk
            exif_chunk = b""

        if chunk_type not in _PNG_DROP_CHUNKS:
            out += chunk
        if chunk_type == b"IEND":
            break

    return bytes(out)


# --------------------------------------------------------------------------
# WebP
# --------------------------------------------------------------------------
def _riff_chunk(fourcc: bytes, payload: bytes) -> bytes:
    pad = b"\x00" if len(payload) % 2 else b""
    return fourcc + struct.pack("<I", len(payload)) + payload + pad


def _strip_webp(data: bytes) -> bytes:
    riff_size = struct.unpack("<I", data[4:8])[0]
    end_of_riff = min(len(data), 8 + riff_size)
    orientation = _read_orientation(data)

    chunks: list[tuple[bytes, bytes]] = []
    pos = 12
    while pos + 8 <= end_of_riff:
        fourcc = data[pos : pos + 4]
        length = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        payload_end = pos + 8 + length
        if payload_end > end_of_riff:
            raise ValueError("WebP のチャンクが途中で切れています")
        chunks.append((fourcc, data[pos + 8 : payload_end]))
        pos = payload_end + (length % 2)

    kept = [(fourcc, payload) for fourcc, payload in chunks if fourcc not in (b"EXIF", b"XMP ")]
    has_vp8x = any(fourcc == b"VP8X" for fourcc, _ in kept)
    keep_orientation = orientation is not None and has_vp8x
    if keep_orientation:
        # WebP の EXIF チャンクも "Exif\0\0" ヘッダを含まない TIFF。画像データの後ろに置く
        kept.append((b"EXIF", _orientation_only_exif(orientation)[6:]))  # type: ignore[arg-type]

    body = bytearray(b"WEBP")
    for fourcc, payload in kept:
        if fourcc == b"VP8X":
            flags = payload[0] & ~(_WEBP_FLAG_EXIF | _WEBP_FLAG_XMP)
            if keep_orientation:
                flags |= _WEBP_FLAG_EXIF
            payload = bytes((flags,)) + payload[1:]
        body += _riff_chunk(fourcc, payload)

    return b"RIFF" + struct.pack("<I", len(body)) + bytes(body)


# --------------------------------------------------------------------------
# 公開 API
# --------------------------------------------------------------------------
def strip_metadata_bytes(data: bytes) -> bytes:
    """メタデータを取り除いたファイル内容を返す。"""
    fmt = _detect_format(data[:12])
    if fmt == "jpeg":
        return _strip_jpeg(data)
    if fmt == "png":
        return _strip_png(data)
    if fmt == "webp":
        return _strip_webp(data)
    raise UnsupportedFormatError("メタデータの削除は JPEG / PNG / WebP のみ対応しています")


def strip_metadata(file_path: str) -> bool:
    """ファイルのメタデータを削除して上書き保存する。

    変更がなければ書き込まず False を返す。書き込みは同じフォルダの一時ファイルに
    書いてから置き換えるため、途中で失敗しても元のファイルは壊れない。
    更新日時などの属性は元のファイルから引き継ぐ (更新日時順の並びを変えないため)。
    """
    with open(file_path, "rb") as f:
        data = f.read()
    stripped = strip_metadata_bytes(data)
    if stripped == data:
        return False

    # 書き出した結果が画像として読めることを確かめてから置き換える
    try:
        with Image.open(io.BytesIO(stripped)) as image:
            image.verify()
    except Exception as e:
        raise ValueError(f"削除後のデータを画像として読み込めませんでした: {e}") from e

    directory = os.path.dirname(os.path.abspath(file_path))
    fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".hiyoko-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(stripped)
        shutil.copystat(file_path, temp_path)
        os.replace(temp_path, file_path)
    except BaseException:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
    return True
