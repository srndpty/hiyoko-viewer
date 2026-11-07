"""画像ファイルからメタデータを削除して上書き保存する。Qt 非依存。

画像データ自体は再エンコードせず、JPEG のセグメント / PNG のチャンク / WebP の
チャンク単位で取り除くため画質は劣化しない。

「残すもの」を列挙する allowlist 方式で、表示・アニメーション・色再現に必要なもの以外は
未知のものも含めてすべて削除する。

残すもの: 画像の向き (Exif Orientation のみを入れ直す)、ICC カラープロファイル、
画素データと、その描画・アニメーション・色再現に必要な情報。
消すもの: 上記以外すべて。Exif (GPS・撮影情報・MakerNote 等)、XMP、IPTC、コメント、
PNG のテキストチャンク (AI 生成パラメータ)、C2PA、JFIF / JFXX のサムネイル、
JPEG 末尾の追加データ (モーションフォトの動画や HDR ゲインマップ等)、独自チャンクなど。
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import struct
import tempfile
import zlib

from PIL import Image, ImageSequence

_ORIENTATION_TAG = 0x0112

_JPEG_SOI = b"\xff\xd8"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# JPEG で残すマーカー (APPn / COM 以外)。SOFn・DHT・DAC・DQT・DRI・SOS・DNL・DHP・EXP
_JPEG_KEEP_MARKERS = (
    set(range(0xC0, 0xD0)) - {0xC8}  # 0xC8 (JPG) は予約済み拡張なので削除
) | {0xDA, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF}

# PNG で残すチャンク。描画・アニメーション・色再現に必要なもの
_PNG_KEEP_CHUNKS = {
    # 必須
    b"IHDR",
    b"PLTE",
    b"IDAT",
    b"IEND",
    # 透過・背景
    b"tRNS",
    b"bKGD",
    # 色管理 (iCCP は下で名前を書き換えて残す)
    b"cHRM",
    b"gAMA",
    b"sBIT",
    b"sRGB",
    b"cICP",
    b"mDCV",
    b"cLLI",
    # 物理的な画素サイズ (DPI)
    b"pHYs",
    # APNG
    b"acTL",
    b"fcTL",
    b"fdAT",
}

# WebP で残すチャンク。画像データ・アルファ・アニメーション・ICC
_WEBP_KEEP_CHUNKS = {b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ANIM", b"ANMF", b"ICCP"}

# WebP VP8X のフラグ
_WEBP_FLAG_EXIF = 0x08
_WEBP_FLAG_XMP = 0x04


class UnsupportedFormatError(ValueError):
    """メタデータ削除に対応していない形式・ファイル。"""


def _detect_format(head: bytes) -> str | None:
    if head.startswith(_JPEG_SOI + b"\xff"):
        return "jpeg"
    if head.startswith(_PNG_SIGNATURE):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _file_type_problem(file_path: str) -> str | None:
    """上書きすると意図しない結果になるファイル種別なら、その理由を返す。"""
    st = os.lstat(file_path)
    reparse_tag = getattr(st, "st_reparse_tag", 0)
    # OneDrive などのクラウドファイルもリパースポイントだが、置き換えて問題ないので許可する。
    # リンク先を持つもの (シンボリックリンク・ジャンクション) だけを拒否する。
    if stat.S_ISLNK(st.st_mode) or reparse_tag in (
        getattr(stat, "IO_REPARSE_TAG_SYMLINK", -1),
        getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1),
    ):
        return "シンボリックリンク / ジャンクションのメタデータは削除できません（リンク先のファイルを開いてください）"
    if not stat.S_ISREG(st.st_mode):
        return "通常のファイルではないため、メタデータを削除できません"
    if st.st_nlink > 1:
        return "ハードリンクされたファイルのメタデータは削除できません（ほかのリンクに元のデータが残るため）"
    return None


def strip_unsupported_reason(file_path: str) -> str | None:
    """メタデータを削除できないファイルなら理由を、削除できるなら None を返す。"""
    try:
        with open(file_path, "rb") as f:
            head = f.read(12)
        problem = _file_type_problem(file_path)
    except OSError as e:
        return f"ファイルを読み込めません: {e}"
    if _detect_format(head) is None:
        return "メタデータの削除は JPEG / PNG / WebP のみ対応しています"
    return problem


def can_strip_metadata(file_path: str) -> bool:
    return strip_unsupported_reason(file_path) is None


def _read_orientation(data: bytes) -> int | None:
    """回転・反転が必要な Orientation (2〜8) を返す。不要なら None。

    Exif が壊れていて向きが分からない場合は、黙って向きを失わないよう例外にする。
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            orientation = image.getexif().get(_ORIENTATION_TAG)
    except Exception as e:
        raise ValueError(f"Exif を解析できないため、画像の向きを保持できません: {e}") from e
    if isinstance(orientation, int) and 2 <= orientation <= 8:
        return orientation
    # 1 (そのまま) や範囲外の値は、一般的なビューアと同じく「回転なし」とみなす
    return None


def _orientation_only_tiff(orientation: int) -> bytes:
    """Orientation だけを含む Exif の TIFF 本体 ("Exif\\0\\0" ヘッダなし) を作る。"""
    exif = Image.Exif()
    exif[_ORIENTATION_TAG] = orientation
    data = exif.tobytes()
    return data[6:] if data.startswith(b"Exif\x00\x00") else data


# --------------------------------------------------------------------------
# JPEG
# --------------------------------------------------------------------------
def _sanitize_jpeg_app_segment(marker: int, payload: bytes, state: dict) -> bytes | None:
    """残す APPn セグメントのペイロードを返す。削除するなら None。"""
    if marker == 0xE0:
        # JFIF は最初の 1 つだけ、埋め込みサムネイルを外して残す (JFXX 拡張は削除)
        if payload.startswith(b"JFIF\x00") and len(payload) >= 14 and not state["jfif"]:
            state["jfif"] = True
            return payload[:12] + b"\x00\x00"
        return None
    if marker == 0xE2 and payload.startswith(b"ICC_PROFILE\x00"):
        return payload  # MPF / FlashPix など他の APP2 は削除
    if marker == 0xEE and payload.startswith(b"Adobe") and len(payload) >= 12:
        # Adobe は色変換の指定 (消すと色が変わり得る)。規定の 12 バイトだけ残す
        if state["adobe"]:
            return None
        state["adobe"] = True
        return payload[:12]
    return None


def _jpeg_segment(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def _strip_jpeg(data: bytes) -> bytes:
    out = bytearray(_JPEG_SOI)
    orientation = _read_orientation(data)
    exif_segment = b""
    if orientation is not None:
        exif_segment = _jpeg_segment(0xE1, b"Exif\x00\x00" + _orientation_only_tiff(orientation))
    inserted_exif = False
    state = {"jfif": False, "adobe": False}

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
            pos += length

            # Exif は APP0 (JFIF) の直後、それ以外のセグメントより前に置く
            if not inserted_exif and marker != 0xE0:
                out += exif_segment
                inserted_exif = True

            if 0xE0 <= marker <= 0xEF:
                kept = _sanitize_jpeg_app_segment(marker, payload, state)
                if kept is not None:
                    out += _jpeg_segment(marker, kept)
            elif marker in _JPEG_KEEP_MARKERS:
                out += _jpeg_segment(marker, payload)
            # COM (0xFE)・予約マーカー・未知のセグメントは削除

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
        exif_chunk = _png_chunk(b"eXIf", _orientation_only_tiff(orientation))

    pos = len(_PNG_SIGNATURE)
    while True:
        if pos + 8 > len(data):
            raise ValueError("PNG の IEND チャンクが見つかりません")
        length, chunk_type = struct.unpack(">I4s", data[pos : pos + 8])
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("PNG のチャンクが途中で切れています")
        payload = data[pos + 8 : pos + 8 + length]
        chunk = data[pos:end]
        pos = end

        # eXIf は最初の画像データより前に置く必要がある
        if exif_chunk and chunk_type in (b"IDAT", b"acTL", b"fcTL"):
            out += exif_chunk
            exif_chunk = b""

        if chunk_type in _PNG_KEEP_CHUNKS:
            out += chunk
        elif chunk_type == b"iCCP":
            # プロファイル名には任意の文字列を入れられるので、固定の名前に置き換える
            separator = payload.find(b"\x00")
            if separator < 0:
                raise ValueError("PNG の iCCP チャンクが不正です")
            out += _png_chunk(b"iCCP", b"ICC Profile" + payload[separator:])
        elif chunk_type[0] & 0x20 == 0:
            # 未知の必須チャンク (先頭が大文字) は消すと画像が壊れ得るので処理を断る
            name = chunk_type.decode("latin-1")
            raise ValueError(f"未知の必須チャンク {name!r} を含む PNG には対応していません")
        # それ以外 (テキスト・Exif・独自の補助チャンクなど) は削除

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
    end_of_riff = 8 + riff_size
    if end_of_riff > len(data):
        raise ValueError("WebP のデータが途中で切れています")
    orientation = _read_orientation(data)

    chunks: list[tuple[bytes, bytes]] = []
    pos = 12
    while pos < end_of_riff:
        if pos + 8 > end_of_riff:
            raise ValueError("WebP のチャンクが途中で切れています")
        fourcc = data[pos : pos + 4]
        length = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        payload_end = pos + 8 + length
        if payload_end > end_of_riff:
            raise ValueError("WebP のチャンクが途中で切れています")
        chunks.append((fourcc, data[pos + 8 : payload_end]))
        pos = payload_end + (length % 2)

    # EXIF / XMP / C2PA / 未知のチャンクはすべて削除
    kept = [(fourcc, payload) for fourcc, payload in chunks if fourcc in _WEBP_KEEP_CHUNKS]
    has_vp8x = any(fourcc == b"VP8X" for fourcc, _ in kept)
    keep_orientation = orientation is not None and has_vp8x
    if keep_orientation:
        # WebP の EXIF チャンクは "Exif\0\0" ヘッダなしの TIFF。画像データの後ろに置く
        kept.append((b"EXIF", _orientation_only_tiff(orientation)))  # type: ignore[arg-type]

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
# 検証・書き込み
# --------------------------------------------------------------------------
def _frame_digests(data: bytes, max_frames: int | None = None) -> list[tuple]:
    """全フレームを実際にデコードし、各フレームのサイズ・モード・画素のハッシュを返す。"""
    digests = []
    with Image.open(io.BytesIO(data)) as image:
        for index, frame in enumerate(ImageSequence.Iterator(image)):
            if max_frames is not None and index >= max_frames:
                break
            frame.load()
            pixels = hashlib.sha256(frame.tobytes()).hexdigest()
            digests.append((frame.size, frame.mode, pixels))
    return digests


def _verify_same_pixels(original: bytes, stripped: bytes, fmt: str) -> None:
    """削除後のデータを全フレームデコードし、元画像と画素が一致することを確かめる。"""
    try:
        after = _frame_digests(stripped)
    except Exception as e:
        raise ValueError(f"削除後のデータを画像として読み込めませんでした: {e}") from e

    # JPEG の元画像は MPF で HDR ゲインマップ等を 2 フレーム目以降に持つことがあるが、
    # それは削除対象なので 1 フレーム目 (本体) だけを比べる
    if fmt == "jpeg" and len(after) != 1:
        raise ValueError("削除後の JPEG に複数の画像が残っています")
    try:
        before = _frame_digests(original, max_frames=len(after) if fmt == "jpeg" else None)
    except Exception as e:
        raise ValueError(f"元の画像を最後まで読み込めないため、安全に処理できません: {e}") from e

    if before != after:
        raise ValueError("削除後の画像が元の画像と一致しません")


def _replace_file(temp_path: str, file_path: str) -> None:
    """temp_path の内容で file_path を置き換える。

    Windows では ReplaceFileW を使い、元ファイルの ACL・属性・作成日時・
    代替データストリームを引き継ぐ。
    """
    if os.name != "nt":
        os.replace(temp_path, file_path)
        return

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    replace_file = kernel32.ReplaceFileW
    replace_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    replace_file.restype = wintypes.BOOL

    # バックアップ名を指定しておくと、途中で失敗しても元ファイルを取り戻せる
    backup_path = temp_path + ".bak"
    if replace_file(file_path, temp_path, backup_path, 0, None, None):
        try:
            os.remove(backup_path)
        except OSError:
            pass
        return

    error = ctypes.get_last_error()
    error_unable_to_move_replacement_2 = 1177
    if error == error_unable_to_move_replacement_2 and os.path.exists(backup_path):
        # 元ファイルはバックアップ名に移動済み。元の名前に戻す
        os.replace(backup_path, file_path)
    raise ctypes.WinError(error)


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

    変更がなければ書き込まず False を返す。置き換える前に全フレームをデコードして
    元画像と画素が一致することを確かめ、同じフォルダの一時ファイルに書いてから
    置き換えるため、途中で失敗しても元のファイルは壊れない。
    更新日時は元のファイルから引き継ぐ (更新日時順の並びを変えないため)。
    """
    problem = _file_type_problem(file_path)
    if problem:
        raise UnsupportedFormatError(problem)

    with open(file_path, "rb") as f:
        data = f.read()
    fmt = _detect_format(data[:12])
    stripped = strip_metadata_bytes(data)
    if stripped == data:
        return False
    _verify_same_pixels(data, stripped, fmt or "")

    directory = os.path.dirname(os.path.abspath(file_path))
    fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".hiyoko-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(stripped)
            f.flush()
            os.fsync(f.fileno())
        shutil.copystat(file_path, temp_path)
        _replace_file(temp_path, file_path)
    except BaseException:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
    return True
