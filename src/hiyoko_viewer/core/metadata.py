"""画像メタデータ（AI生成パラメータ・Exif・GPS・XMP・IPTC・ICC）の抽出。Qt 非依存・PIL のみ。"""

from __future__ import annotations

import io
import json
import math
from xml.etree import ElementTree

from PIL import ExifTags, Image

NO_METADATA_TEXT = "この画像には表示可能なメタデータが見つかりませんでした。"


def _decode_exif_user_comment(raw: object) -> str | None:
    """EXIF UserComment を先頭 8 バイトの文字コード指定子に従ってデコードする。

    bytes 以外（既にデコード済みなど）や中身が空の場合は None を返す。
    UNICODE 指定子の本体は UTF-16 のため、UTF-8 でデコードすると文字化けする。
    """
    if not isinstance(raw, bytes):
        return None

    if raw.startswith(b"UNICODE\x00"):
        body = raw[8:]
        # バイトオーダーは BOM があればそれに従い、無ければ慣例的に UTF-16-LE とみなす
        if body.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = body.decode("utf-16", errors="ignore")
        else:
            text = body.decode("utf-16-le", errors="ignore")
    elif raw.startswith(b"ASCII\x00\x00\x00"):
        text = raw[8:].decode("ascii", errors="ignore")
    elif raw.startswith(b"\x00" * 8):
        # 文字コード未指定。慣例的に UTF-8 として扱う
        text = raw[8:].decode("utf-8", errors="ignore")
    else:
        # 指定子の無い独自形式。全体を UTF-8 として読む
        text = raw.decode("utf-8", errors="ignore")

    text = text.replace("\x00", "").strip()
    return text or None


_SECTION_END = "\n" + "-" * 20 + "\n"
_MAX_VALUE_LEN = 100
_MAX_XMP_RAW_LEN = 2000

# サブ IFD へのポインタ。値はオフセットに過ぎないので表示せず、中身を展開して表示する
_IFD_POINTER_TAGS = {int(ExifTags.IFD.Exif), int(ExifTags.IFD.GPSInfo), int(ExifTags.IFD.Interop)}

_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_XMP_META_NS = "adobe:ns:meta/"

# IPTC-IIM の主なデータセット (record, dataset) → 名前
_IPTC_NAMES = {
    (2, 5): "ObjectName",
    (2, 25): "Keywords",
    (2, 40): "SpecialInstructions",
    (2, 55): "DateCreated",
    (2, 60): "TimeCreated",
    (2, 80): "By-line",
    (2, 85): "By-lineTitle",
    (2, 90): "City",
    (2, 92): "Sub-location",
    (2, 95): "Province-State",
    (2, 101): "Country",
    (2, 105): "Headline",
    (2, 110): "Credit",
    (2, 115): "Source",
    (2, 116): "CopyrightNotice",
    (2, 120): "Caption-Abstract",
    (2, 122): "Writer-Editor",
}


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"--- {title} ---\n", *lines, _SECTION_END]


def _truncate(text: str, limit: int = _MAX_VALUE_LEN) -> str:
    return text[:limit] + "..." if len(text) > limit else text


def _format_value(value: object) -> str:
    """表示用に値を文字列化する。読めないバイナリはサイズだけ示す。"""
    if isinstance(value, bytes):
        stripped = value.rstrip(b"\x00")
        if stripped and all(32 <= c < 127 for c in stripped):
            return _truncate(stripped.decode("ascii"))
        return f"<バイナリ {len(value)} bytes>"
    return _truncate(str(value))


def _to_float(value: object) -> float:
    """IFDRational / (分子, 分母) タプル / 数値を float にする。"""
    if isinstance(value, tuple) and len(value) == 2:
        return value[0] / value[1]
    return float(value)  # type: ignore[arg-type]


def _format_exif_value(name: str, value: object) -> str:
    try:
        if name == "ExposureTime":
            seconds = _to_float(value)
            if 0 < seconds < 1:
                return f"1/{round(1 / seconds)} 秒"
            return f"{seconds:g} 秒"
        if name == "FNumber":
            return f"f/{_to_float(value):g}"
        if name == "FocalLength":
            return f"{_to_float(value):g} mm"
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return _format_value(value)


def _tag_lines(tags: dict, names: dict) -> list[str]:
    lines = []
    for key, value in tags.items():
        name = names.get(key) or (f"0x{key:04X}" if isinstance(key, int) else str(key))
        if name == "UserComment":
            decoded = _decode_exif_user_comment(value)
            if decoded:
                lines.append(f"{name}: {_truncate(decoded)}")
                continue
        lines.append(f"{name}: {_format_exif_value(name, value)}")
    return lines


def _gps_decimal(dms: object, ref: object) -> float | None:
    """GPS の (度, 分, 秒) と N/S/E/W から 10 進の度数を求める。"""
    try:
        degrees, minutes, seconds = (_to_float(v) for v in dms)  # type: ignore[union-attr]
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    result = degrees + minutes / 60 + seconds / 3600
    if not math.isfinite(result):
        return None
    if isinstance(ref, bytes):
        ref = ref.decode("ascii", errors="ignore")
    if str(ref).strip().upper() in ("S", "W"):
        result = -result
    return result


def _exif_sections(image: Image.Image) -> list[str]:
    exif = image.getexif()
    if not exif:
        return []

    def sub_ifd(ifd: ExifTags.IFD) -> dict:
        get_ifd = getattr(exif, "get_ifd", None)
        if get_ifd is None:
            return {}
        try:
            return dict(get_ifd(ifd))
        except Exception:
            return {}

    base = {k: v for k, v in exif.items() if k not in _IFD_POINTER_TAGS}
    exif_ifd = sub_ifd(ExifTags.IFD.Exif)
    gps_ifd = sub_ifd(ExifTags.IFD.GPSInfo)
    interop_ifd = sub_ifd(ExifTags.IFD.Interop)

    parts: list[str] = []

    # UserComment は本来 Exif IFD にあるが、IFD0 に置くソフトもあるので両方見る
    raw_comment = exif_ifd.get(0x9286, base.get(0x9286))
    decoded_comment = _decode_exif_user_comment(raw_comment)
    if decoded_comment:
        parts += _section("AI生成パラメータ (UserComment)", [decoded_comment])

    if base:
        parts += _section("Exif 基本情報", _tag_lines(base, ExifTags.TAGS))
    if exif_ifd:
        parts += _section("Exif 撮影情報", _tag_lines(exif_ifd, ExifTags.TAGS))
    if interop_ifd:
        parts += _section("Exif 互換性情報", _tag_lines(interop_ifd, ExifTags.TAGS))
    if gps_ifd:
        gps_lines = []
        lat = _gps_decimal(gps_ifd.get(2), gps_ifd.get(1))
        lon = _gps_decimal(gps_ifd.get(4), gps_ifd.get(3))
        if lat is not None and lon is not None:
            gps_lines.append(f"緯度経度: {lat:.6f}, {lon:.6f}")
        gps_lines += _tag_lines(gps_ifd, ExifTags.GPSTAGS)
        parts += _section("GPS 位置情報", gps_lines)

    return parts


def _xmp_lines(raw: bytes | str) -> list[str]:
    """XMP (RDF/XML) を「プレフィックス:プロパティ: 値」の平坦な行に変換する。"""
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    prefixes: dict[str, str] = {}
    root = None
    try:
        for event, item in ElementTree.iterparse(io.BytesIO(data), events=("start-ns", "end")):
            if event == "start-ns":
                prefix, uri = item
                prefixes.setdefault(uri, prefix)
            else:
                root = item
    except ElementTree.ParseError:
        root = None

    if root is None:
        text = data.decode("utf-8", errors="replace").strip("\x00 \r\n\t")
        return [_truncate(text, _MAX_XMP_RAW_LEN)] if text else []

    def split(tag: str) -> tuple[str, str]:
        if tag.startswith("{"):
            uri, local = tag[1:].split("}", 1)
            return uri, local
        return "", tag

    def qname(tag: str) -> str:
        uri, local = split(tag)
        prefix = prefixes.get(uri)
        return f"{prefix}:{local}" if prefix else local

    lines: list[str] = []

    def walk(element: ElementTree.Element, path: str) -> None:
        uri, _ = split(element.tag)
        # rdf:RDF / rdf:Description / rdf:Seq / rdf:li などの構造用要素はパスに含めない
        if uri not in (_RDF_NS, _XMP_META_NS):
            name = qname(element.tag)
            path = f"{path}/{name}" if path else name
        for attr, value in element.attrib.items():
            if split(attr)[0] in (_RDF_NS, _XMP_META_NS):
                continue
            key = f"{path}/{qname(attr)}" if path else qname(attr)
            lines.append(f"{key}: {_truncate(value)}")
        text = (element.text or "").strip()
        if text and len(element) == 0 and path:
            lines.append(f"{path}: {_truncate(text)}")
        for child in element:
            walk(child, path)

    walk(root, "")
    return lines


def _iptc_lines(image: Image.Image) -> list[str]:
    try:
        from PIL import IptcImagePlugin

        iptc = IptcImagePlugin.getiptcinfo(image)
    except Exception:
        return []
    if not iptc:
        return []

    lines = []
    for key in sorted(iptc):
        values = iptc[key]
        if not isinstance(values, list):
            values = [values]
        texts = [
            v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v) for v in values
        ]
        name = _IPTC_NAMES.get(key) or f"{key[0]}:{key[1]}"
        lines.append(f"{name}: {_truncate(', '.join(texts))}")
    return lines


def _icc_lines(icc: bytes) -> list[str]:
    description = None
    try:
        from PIL import ImageCms

        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        description = ImageCms.getProfileDescription(profile).strip()
    except Exception:
        pass
    lines = [f"プロファイル: {description}"] if description else []
    lines.append(f"サイズ: {len(icc)} bytes")
    return lines


def _other_metadata_sections(image: Image.Image) -> list[str]:
    info = image.info or {}
    parts: list[str] = []

    # JPEG の COM セグメント（PNG の NovelAI 'Comment' とは別キー）
    comment = info.get("comment")
    if comment:
        if isinstance(comment, bytes):
            comment = comment.decode("utf-8", errors="replace")
        parts += _section("JPEG コメント", [comment])

    xmp = info.get("xmp") or info.get("XML:com.adobe.xmp")
    if xmp:
        xmp_lines = _xmp_lines(xmp)
        if xmp_lines:
            parts += _section("XMP", xmp_lines)

    iptc_lines = _iptc_lines(image)
    if iptc_lines:
        parts += _section("IPTC", iptc_lines)

    icc = info.get("icc_profile")
    if icc:
        parts += _section("ICC カラープロファイル", _icc_lines(icc))

    return parts


def extract_metadata_text(image: Image.Image) -> str:
    metadata_parts = []

    # --- 1. PNGの parameters (AIプロンプト) をチェック ---
    if image.info:
        # NovelAI は 'Comment' キーにJSON形式で全パラメータを格納する
        if "Comment" in image.info:
            try:
                nai_data = json.loads(image.info["Comment"])

                metadata_parts.append("--- NovelAI パラメータ (JSON) ---\n")
                pretty_json = json.dumps(nai_data, indent=2, ensure_ascii=False)
                metadata_parts.append(pretty_json)
                metadata_parts.append("\n" + "-" * 20 + "\n")

            except json.JSONDecodeError:
                metadata_parts.append("--- NovelAI パラメータ (Comment) ---\n")
                metadata_parts.append(image.info["Comment"])
                metadata_parts.append("\n" + "-" * 20 + "\n")

        # Stable Diffusion WebUI (A1111) は 'parameters' キーを使用
        elif "parameters" in image.info:
            metadata_parts.append("--- AI生成パラメータ (PNG) ---\n")
            metadata_parts.append(image.info["parameters"])
            metadata_parts.append("\n" + "-" * 20 + "\n")

        # 念のため、'Description' も表示する (プレーンなプロンプトが入っている場合がある)
        if "Description" in image.info and "Comment" not in image.info:
            metadata_parts.append("--- AI生成パラメータ (Description) ---\n")
            metadata_parts.append(image.info["Description"])
            metadata_parts.append("\n" + "-" * 20 + "\n")

    # --- 2. Exif / GPS ---
    metadata_parts.extend(_exif_sections(image))

    # --- 3. Exif 以外のメタデータ (JPEG コメント / XMP / IPTC / ICC) ---
    metadata_parts.extend(_other_metadata_sections(image))

    if not metadata_parts:
        return NO_METADATA_TEXT
    return "\n".join(metadata_parts)


def load_metadata_text(file_path: str) -> str:
    try:
        with Image.open(file_path) as image:
            return extract_metadata_text(image)
    except Exception as e:
        return f"メタデータの読み込み中にエラーが発生しました:\n{e}"
