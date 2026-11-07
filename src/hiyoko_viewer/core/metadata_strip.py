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

対象は画像ファイルの中身だけ。ファイル名や、代替データストリーム (ADS)・ACL などの
ファイルシステム上の情報は変更しない (ADS にも任意の情報を格納できる点に注意)。

上書きの手順と、異常時に元データが残り得る場所:
1. 同じフォルダの一時ファイル ``.hiyoko-strip-*.tmp`` に削除後の内容を書く
   (中身は削除後のデータなので、残っても元のメタデータは含まない)。
2. Windows では ReplaceFileW で置き換え、元ファイルをバックアップ ``.hiyoko-strip-*.bak``
   に退避する。バックアップの中身が読み込んだ内容と一致するか確かめ (一致しなければ
   処理中に他のプロセスが書き換えたとみなして元に戻す)、確認後に削除する。
3. バックアップを削除できなかった場合は BackupCleanupError で必ず報告する。
   ReplaceFileW の成功からバックアップ削除までの間にプロセスが異常終了した場合は、
   元のメタデータを含む ``.hiyoko-strip-*.bak`` が残り得る (仕様上の制約)。
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import stat
import struct
import tempfile
import time
import zlib

from PIL import Image, ImageSequence

logger = logging.getLogger(__name__)

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
            if image.format == "PNG":
                # PNG は画像データより後ろに eXIf があると、読み込み後でないと見えない
                image.load()
            orientation = image.getexif().get(_ORIENTATION_TAG)
    except Exception as e:
        raise ValueError(f"Exif を解析できないため、画像の向きを保持できません: {e}") from e
    return _normalize_orientation(orientation)


def _normalize_orientation(orientation: object) -> int | None:
    """Orientation を「回転なし (None)」か 2〜8 に正規化する。

    無い・1 は回転なし。それ以外の値や型は、ビューアによって解釈が分かれ表示状態を
    保証できないため、処理を断る。
    """
    if orientation is None or (type(orientation) is int and orientation == 1):
        return None
    if type(orientation) is int and 2 <= orientation <= 8:
        return orientation
    raise ValueError(
        f"Exif の Orientation が不正な値 ({orientation!r}) のため、" "画像の向きを保持できません"
    )


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
class FileChangedError(RuntimeError):
    """処理中に元のファイルが他のプロセスによって変更された。元ファイルはそのまま。"""


class ReplaceFailedError(OSError):
    """ファイルの置き換えに失敗した。メッセージに状態と関連ファイルのパスを含む。"""


class BackupCleanupError(RuntimeError):
    """メタデータは削除できたが、元のデータを含むバックアップを削除できなかった。"""

    def __init__(self, backup_path: str, cause: BaseException) -> None:
        super().__init__(
            "メタデータは削除しましたが、元のデータ（削除前のメタデータを含む）のバックアップを"
            f"削除できませんでした。手動で削除してください:\n{backup_path}\n({cause})"
        )
        self.backup_path = backup_path


_TEMP_PREFIX = ".hiyoko-strip-"

# Windows では ReplaceFileW を使う (テストで差し替えられるようモジュール変数にしている)
_USE_REPLACE_FILE = os.name == "nt"

# バックアップ削除の再試行間隔 (秒)。ウイルス対策や同期ソフトが一時的に掴むことがあるため
_BACKUP_REMOVE_RETRY_DELAYS = (0.1, 0.3, 1.0)


def _image_signature(data: bytes, max_frames: int | None = None) -> dict:
    """全フレームを実際にデコードし、表示結果に関わる情報をまとめる。

    フレームごとのサイズ・モード・表示時間・画素のハッシュと、ループ回数・
    ICC プロファイル・Orientation を含む。
    """
    frames = []
    with Image.open(io.BytesIO(data)) as image:
        for index, frame in enumerate(ImageSequence.Iterator(image)):
            if max_frames is not None and index >= max_frames:
                break
            frame.load()
            pixels = hashlib.sha256(frame.tobytes()).hexdigest()
            frames.append((frame.size, frame.mode, frame.info.get("duration"), pixels))
        image.seek(0)
        return {
            "frames": frames,
            "loop": image.info.get("loop"),
            "icc_profile": image.info.get("icc_profile") or None,
            "orientation": _normalize_orientation(image.getexif().get(_ORIENTATION_TAG)),
        }


_SIGNATURE_LABELS = {
    "frames": "画素・フレーム構成・表示時間",
    "loop": "ループ回数",
    "icc_profile": "ICC カラープロファイル",
    "orientation": "画像の向き",
}


def _verify_same_image(original: bytes, stripped: bytes, fmt: str) -> None:
    """削除後のデータを全フレームデコードし、表示結果が元画像と一致することを確かめる。"""
    try:
        after = _image_signature(stripped)
    except Exception as e:
        raise ValueError(f"削除後のデータを画像として読み込めませんでした: {e}") from e

    # JPEG の元画像は MPF で HDR ゲインマップ等を 2 フレーム目以降に持つことがあるが、
    # それは削除対象なので 1 フレーム目 (本体) だけを比べる
    if fmt == "jpeg" and len(after["frames"]) != 1:
        raise ValueError("削除後の JPEG に複数の画像が残っています")
    try:
        before = _image_signature(original, max_frames=1 if fmt == "jpeg" else None)
    except Exception as e:
        raise ValueError(f"元の画像を最後まで読み込めないため、安全に処理できません: {e}") from e
    if fmt == "jpeg":
        before["loop"] = after["loop"]  # MPO 由来の情報は比較しない

    for key, label in _SIGNATURE_LABELS.items():
        if before[key] != after[key]:
            raise ValueError(f"削除後の画像が元の画像と一致しません（{label}）")


def _file_identity(st: os.stat_result) -> tuple:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _win_replace_file(replaced: str, replacement: str, backup: str) -> int:
    """ReplaceFileW を呼ぶ。成功なら 0、失敗なら Win32 エラーコードを返す。"""
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
    if replace_file(replaced, replacement, backup, 0, None, None):
        return 0
    return ctypes.get_last_error() or -1


def _remove_backup(backup_path: str) -> None:
    """元データを含むバックアップを削除する。消せなければ BackupCleanupError。"""
    last_error: OSError | None = None
    for delay in (0.0, *_BACKUP_REMOVE_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            os.remove(backup_path)
            return
        except FileNotFoundError:
            return
        except OSError as e:
            last_error = e
    logger.error("バックアップを削除できません: %s (%s)", backup_path, last_error)
    raise BackupCleanupError(backup_path, last_error)  # type: ignore[arg-type]


def _sha256_or_none(path: str) -> str | None:
    try:
        return _sha256_file(path)
    except OSError:
        return None


def _recover_after_replace_failure(
    file_path: str, temp_path: str, backup_path: str, error_code: int, expected_sha256: str
) -> ReplaceFailedError:
    """ReplaceFileW の失敗後、エラーコードではなく実際のファイルの状態を見て復旧する。

    元の場所のファイルが読み込み時と同じ内容 (expected_sha256) だと確認できた場合だけ
    一時ファイルを削除し「変更されていません」と報告する。確認できない場合は
    調査・手動復旧のため関連ファイルを残し、パスをメッセージに含める。
    """
    logger.error(
        "ReplaceFileW failed: code=%s file=%s temp=%s backup=%s",
        error_code,
        file_path,
        temp_path,
        backup_path,
    )
    detail = f"ファイルの置き換えに失敗しました (Win32 エラー {error_code})"
    keep_note = f"\n対象: {file_path}\n削除後のデータ: {temp_path}"
    original_in_place = os.path.lexists(file_path)
    backup_exists = os.path.lexists(backup_path)

    if original_in_place and not backup_exists:
        # 1175 / 1176 など: 元ファイルは元の場所にあるはず。中身まで確かめる
        if _sha256_or_none(file_path) == expected_sha256:
            _remove_quietly(temp_path)
            return ReplaceFailedError(f"{detail}。元のファイルは変更されていません。")
        return ReplaceFailedError(
            f"{detail}。元の場所のファイルが読み込み時と異なります"
            f"（他のプログラムによる変更の可能性）。関連ファイルを残しています。{keep_note}"
        )

    if not original_in_place and backup_exists:
        # 1177 など: 元ファイルがバックアップ名へ移動済み。元の名前に戻す
        try:
            os.replace(backup_path, file_path)
        except OSError as e:
            logger.error("元ファイルの復元に失敗: %s -> %s (%s)", backup_path, file_path, e)
            return ReplaceFailedError(
                f"{detail}。元のファイルを元の名前に戻せませんでした。\n"
                f"元のファイル: {backup_path}\n削除後のデータ: {temp_path}"
            )
        if _sha256_or_none(file_path) == expected_sha256:
            _remove_quietly(temp_path)
            return ReplaceFailedError(f"{detail}。元のファイルは元の名前に戻しました。")
        return ReplaceFailedError(
            f"{detail}。退避されていたファイルを元の名前に戻しましたが、内容が読み込み時と"
            f"異なります（他のプログラムによる変更の可能性）。関連ファイルを残しています。"
            f"{keep_note}"
        )

    # 想定外の状態。何も消さずに状況を報告する
    return ReplaceFailedError(
        f"{detail}。想定外の状態のため、関連ファイルを残しています。\n"
        f"対象: {file_path} (存在: {original_in_place})\n"
        f"バックアップ: {backup_path} (存在: {backup_exists})\n削除後のデータ: {temp_path}"
    )


def _replace_file(temp_path: str, file_path: str, expected_sha256: str) -> None:
    """temp_path の内容で file_path を置き換える。

    Windows では ReplaceFileW で元ファイルの ACL・属性・作成日時・代替データストリームを
    引き継ぐ。置き換えた元ファイル (バックアップ) の中身が expected_sha256 と異なれば、
    処理中に他のプロセスが書き換えたとみなして元に戻し、FileChangedError を送出する。
    """
    if not _USE_REPLACE_FILE:
        os.replace(temp_path, file_path)
        return

    backup_path = temp_path[: -len(".tmp")] + ".bak"
    error_code = _win_replace_file(file_path, temp_path, backup_path)
    if error_code:
        raise _recover_after_replace_failure(
            file_path, temp_path, backup_path, error_code, expected_sha256
        )

    try:
        backup_matches = _sha256_file(backup_path) == expected_sha256
    except OSError as e:
        logger.warning("バックアップを検証できません: %s (%s)", backup_path, e)
        backup_matches = False
    if not backup_matches:
        # 置き換えたのは読み込んだ時点のファイルではない (または確認できない)。元に戻す
        try:
            os.replace(backup_path, file_path)
        except OSError as e:
            logger.error("元ファイルの復元に失敗: %s -> %s (%s)", backup_path, file_path, e)
            raise ReplaceFailedError(
                "処理中にファイルが変更された可能性があり、元に戻そうとしましたが失敗しました。\n"
                f"元のファイル: {backup_path}"
            ) from e
        raise FileChangedError(
            "処理中にファイルが他のプログラムによって変更されたため、元に戻しました。"
            "もう一度お試しください。"
        )

    _remove_backup(backup_path)


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
    表示結果が元画像と一致することを確かめ、同じフォルダの一時ファイルに書いてから
    置き換えるため、途中で失敗しても元のファイルは壊れない。
    更新日時は元のファイルから引き継ぐ (更新日時順の並びを変えないため)。

    読み込みから置き換えまでの間に他のプロセスがファイルを変更した場合は
    FileChangedError を送出し、元のファイル (変更後の内容) を残す。
    """
    problem = _file_type_problem(file_path)
    if problem:
        raise UnsupportedFormatError(problem)

    with open(file_path, "rb") as f:
        identity = _file_identity(os.fstat(f.fileno()))
        data = f.read()
        if _file_identity(os.fstat(f.fileno())) != identity:
            raise FileChangedError("読み込み中にファイルが変更されました。もう一度お試しください。")
    fmt = _detect_format(data[:12])
    stripped = strip_metadata_bytes(data)
    if stripped == data:
        return False
    _verify_same_image(data, stripped, fmt or "")

    directory = os.path.dirname(os.path.abspath(file_path))
    fd, temp_path = tempfile.mkstemp(dir=directory, prefix=_TEMP_PREFIX, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(stripped)
            f.flush()
            os.fsync(f.fileno())
        shutil.copystat(file_path, temp_path)

        # 置き換え直前にもう一度、リンクへのすり替えや内容の変更がないか確かめる
        problem = _file_type_problem(file_path)
        if problem:
            raise UnsupportedFormatError(problem)
        if _file_identity(os.stat(file_path)) != identity:
            raise FileChangedError(
                "処理中にファイルが他のプログラムによって変更されました。もう一度お試しください。"
            )
    except BaseException:
        _remove_quietly(temp_path)
        raise

    # 置き換え以降の後始末 (一時ファイル・バックアップ) は _replace_file が状態に応じて行う
    _replace_file(temp_path, file_path, hashlib.sha256(data).hexdigest())
    return True
