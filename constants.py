import sys
import os

# --- 定数 ---
SUPPORTED_EXTENSIONS = [
    '.bmp', '.cur', '.gif', '.icns', '.ico', '.jfif', '.jpeg', '.jpg', 
    '.pbm', '.pdf', '.pgm', '.png', '.ppm', '.svg', '.svgz', '.tga', 
    '.tif', '.tiff', '.wbmp', '.webp', '.xbm', '.xpm'
]
OK_FOLDER = "_ok"
NG_FOLDER = "_ng"
ZOOM_IN_FACTOR = 1.15
ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR
WELCOME_TEXT = "ファイル > 開く（Ctrl+O）またはドラッグアンドドロップで読み込む"
NOTICE_TEXT_STYLE = "font-size: 16pt; color: #555;"
DEFAULT_TITLE = "ひよこビューア"

# --- グローバルヘルパー関数 ---
def resource_path(relative_path: str) -> str:
    """ 開発時とPyInstaller実行時の両方で、リソースへの正しいパスを取得する """
    try:
        base_path: str = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)