from __future__ import annotations

# --- 対応拡張子 ---
SUPPORTED_EXTENSIONS = [
    ".bmp",
    ".cur",
    ".gif",
    ".icns",
    ".ico",
    ".jfif",
    ".jpeg",
    ".jpg",
    ".pbm",
    ".pgm",
    ".png",
    ".ppm",
    ".svg",
    ".svgz",
    ".tga",
    ".tif",
    ".tiff",
    ".wbmp",
    ".webp",
    ".xbm",
    ".xpm",
]

# --- 仕分けフォルダ ---
OK_FOLDER = "_ok"
NG_FOLDER = "_ng"

# --- ズーム ---
ZOOM_IN_FACTOR = 1.15
ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR

# --- 表示テキスト/スタイル ---
WELCOME_TEXT = "ファイル > 開く（Ctrl+O）またはドラッグアンドドロップで読み込む"
NOTICE_TEXT_STYLE = "font-size: 16pt; color: #555;"
DEFAULT_TITLE = "ひよこビューア"

# --- QSettings の保存先（組織名/アプリ名）---
SETTINGS_ORG = "HiyokoSoft"
SETTINGS_APP = "HiyokoViewer"
