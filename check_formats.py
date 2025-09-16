import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImageReader

# PyQtのアプリケーションインスタンスを作成する必要がある
# これにより、Qtのプラグインが正しくロードされる
app = QApplication(sys.argv)

# サポートされている画像フォーマットのリストを取得する
supported_formats = QImageReader.supportedImageFormats()

print("あなたの環境のPyQt6がサポートしている画像フォーマット:")
# バイト文字列(b'png')を通常の文字列('png')に変換して表示
format_list = [fmt.data().decode().lower() for fmt in supported_formats]

# 見やすいように整形して出力
print("'." + "', '.".join(format_list) + "'")

# for i in range(0, len(format_list), 8):
#     print("  ".join(format_list[i:i+8]))