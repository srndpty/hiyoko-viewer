"""画像メタデータ（AI生成パラメータ等）の抽出。Qt 非依存・PIL のみ。"""

from __future__ import annotations

import json

from PIL import Image

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

    # --- 2. Exif データをチェック ---
    exif_data = image.getexif()
    if exif_data:
        from PIL.ExifTags import TAGS

        exif_info = {TAGS.get(key, key): value for key, value in exif_data.items()}

        if "UserComment" in exif_info:
            decoded_comment = _decode_exif_user_comment(exif_info["UserComment"])
            if decoded_comment:
                metadata_parts.append("--- AI生成パラメータ (UserComment) ---\n")
                metadata_parts.append(decoded_comment)
                metadata_parts.append("\n" + "-" * 20 + "\n")

        metadata_parts.append("--- Exif 詳細 ---\n")
        for tag, value in exif_info.items():
            value_str = str(value)
            if len(value_str) > 100:
                value_str = value_str[:100] + "..."
            metadata_parts.append(f"{tag}: {value_str}")

    if not metadata_parts:
        return NO_METADATA_TEXT
    return "\n".join(metadata_parts)


def load_metadata_text(file_path: str) -> str:
    try:
        with Image.open(file_path) as image:
            return extract_metadata_text(image)
    except Exception as e:
        return f"メタデータの読み込み中にエラーが発生しました:\n{e}"
