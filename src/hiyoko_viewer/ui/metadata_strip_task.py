"""メタデータ削除をバックグラウンドで実行するスレッド。

大きなファイル (動画付きのモーションフォト等) では読み込み・全フレームのデコード検証・
書き込みに時間がかかるため、GUI スレッドを塞がないよう別スレッドで行う。
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from ..core.metadata_strip import BackupCleanupError, strip_metadata


class MetadataStripTask(QThread):
    """completed は結果の通知だけで、スレッドの終了は QThread.finished で判断すること。"""

    # (ファイルを書き換えたか, 失敗・警告時の例外 or None)
    completed = pyqtSignal(bool, object)

    def __init__(self, file_path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.file_path = file_path

    def run(self) -> None:
        try:
            changed = strip_metadata(self.file_path)
        except BackupCleanupError as e:
            # ファイル自体は書き換わっている。バックアップが残ったことを警告として伝える
            self.completed.emit(True, e)
            return
        except Exception as e:
            self.completed.emit(False, e)
            return
        self.completed.emit(changed, None)
