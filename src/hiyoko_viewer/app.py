"""アプリケーションのエントリポイント。

二重起動防止（共有メモリ）とインスタンス間通信（ローカルソケット）を行い、
最初のインスタンスのみ ``ImageViewer`` を起動する。
"""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QSharedMemory
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from .core.resources import resource_path
from .ui.main_window import ImageViewer

# アプリケーションごとにユニークなキー（二重起動防止/IPC 用）
APP_UNIQUE_KEY = "hiyoko-viewer-unique-key-for-ipc"


def _forward_to_running_instance() -> None:
    """実行中のインスタンスにファイルパスを渡して、このプロセスは終了する。"""
    socket = QLocalSocket()
    socket.connectToServer(APP_UNIQUE_KEY)
    if socket.waitForConnected(500):  # 500ms 待つ
        # 2番目以降の引数（ファイルパス）をUTF-8でエンコードして送信
        args_to_send = sys.argv[1:] if len(sys.argv) > 1 else []
        data = "\n".join(args_to_send).encode("utf-8")
        socket.write(data)
        socket.waitForBytesWritten(500)


def main() -> int:
    """アプリを起動する。新規起動なら QApplication を実行し、終了コードを返す。"""
    # --- 二重起動防止とインスタンス間通信 ---
    shared_memory = QSharedMemory(APP_UNIQUE_KEY)

    # 以前のインスタンスが異常終了して取り残された共有メモリを掃除する。
    # （Unix系では segment が残ると二度と起動できなくなる。Windowsは自動解放されるため通常no-op）
    if shared_memory.attach():
        shared_memory.detach()

    # create() が False を返す = すでにメモリが確保されている = 他のインスタンスが実行中
    if not shared_memory.create(1):
        _forward_to_running_instance()
        # このインスタンスは役目を終えたので終了
        return 0

    # --- ここから下は、最初のインスタンスのみが実行する ---
    app = QApplication(sys.argv)
    # app.setPalette() よりも強力なスタイルシートで、デフォルトのウィンドウ背景を上書きする
    # これにより、OSがウィンドウの「器」を作成する際のデフォルト色を制御する
    app.setStyleSheet("QMainWindow { background-color: #2d2d2d; }")
    app.setQuitOnLastWindowClosed(False)

    app_icon_path = resource_path("app_icon.ico")
    if os.path.exists(app_icon_path):
        app.setWindowIcon(QIcon(app_icon_path))

    viewer = ImageViewer()

    # 2番目のインスタンスからファイルパスを受け取るためのサーバーをセットアップ
    local_server = QLocalServer()

    def handle_new_connection():
        socket = local_server.nextPendingConnection()
        if socket.waitForReadyRead(500):
            data = socket.readAll().data().decode("utf-8")
            file_paths = data.splitlines()
            if file_paths:
                viewer.load_image_from_path(file_paths[0])
            viewer.show_window()

    local_server.newConnection.connect(handle_new_connection)
    # 異常終了で取り残されたソケット（主にUnix系）を掃除してから listen する
    QLocalServer.removeServer(APP_UNIQUE_KEY)
    local_server.listen(APP_UNIQUE_KEY)

    # 最初の起動時の引数を処理
    if len(sys.argv) > 1:
        initial_file_path = sys.argv[1]
        viewer.load_image_from_path(initial_file_path)

    viewer.show()

    def cleanup_on_quit():
        # 共有メモリを解放する
        shared_memory.detach()

        viewer.worker_thread.quit()
        viewer.worker_thread.wait()
        viewer._save_settings()

    app.aboutToQuit.connect(cleanup_on_quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
