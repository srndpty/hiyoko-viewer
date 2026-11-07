"""メタデータ削除をバックグラウンドで実行するスレッド。

大きなファイル (動画付きのモーションフォト等) では読み込み・全フレームのデコード検証・
書き込みに時間がかかるため、GUI スレッドを塞がないよう別スレッドで行う。
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from ..core.metadata_strip import strip_metadata


class MetadataStripTask(QThread):
    # (変更があったか, 失敗時の例外 or None)
    completed = pyqtSignal(bool, object)

    def __init__(self, file_path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.file_path = file_path

    def run(self) -> None:
        try:
            changed = strip_metadata(self.file_path)
        except Exception as e:
            self.completed.emit(False, e)
            return
        self.completed.emit(changed, None)
