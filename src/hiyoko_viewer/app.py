"""アプリケーションのエントリポイント。

二重起動防止（共有メモリ）とインスタンス間通信（ローカルソケット）を行い、
最初のインスタンスのみ ``ImageViewer`` を起動する。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QSharedMemory
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from .core.resources import resource_path
from .ui.main_window import ImageViewer

logger = logging.getLogger(__name__)

# アプリケーションごとにユニークなキー（二重起動防止/IPC 用）
APP_UNIQUE_KEY = "hiyoko-viewer-unique-key-for-ipc"


def setup_logging() -> None:
    """GUI/PyInstaller(--windowed) 実行では標準出力が見えないため、ファイルに残す。

    %LOCALAPPDATA%\\HiyokoViewer\\logs\\hiyoko-viewer.log（取得できなければ %TEMP%）。
    """
    base_dir = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
    log_dir = Path(base_dir) / "HiyokoViewer" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(log_dir / "hiyoko-viewer.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            encoding="utf-8",
            force=True,
        )
    except OSError:
        # ログ用ディレクトリ/ファイルを用意できなくても起動自体は止めない
        logging.basicConfig(level=logging.INFO, force=True)


# 既存インスタンスへの接続リトライ（ログオン直後は相手の listen が間に合わないことがある）
IPC_CONNECT_ATTEMPTS = 3
IPC_CONNECT_TIMEOUT_MS = 1500


def _forward_to_running_instance() -> bool:
    """実行中のインスタンスにファイルパスを渡す。委譲できたら True を返す。

    False は「既存インスタンスを検出したのに操作を渡せなかった」状態。呼び出し側は
    このプロセスを黙って終わらせてはならない（ユーザーからは「起動しても何も起き
    ない＝フリーズ」に見えるため）。
    """
    # 2番目以降の引数（ファイルパス）をUTF-8でエンコードして送信
    args_to_send = sys.argv[1:] if len(sys.argv) > 1 else []
    data = "\n".join(args_to_send).encode("utf-8")

    for attempt in range(1, IPC_CONNECT_ATTEMPTS + 1):
        socket = QLocalSocket()
        socket.connectToServer(APP_UNIQUE_KEY)
        if socket.waitForConnected(IPC_CONNECT_TIMEOUT_MS):
            socket.write(data)
            socket.waitForBytesWritten(IPC_CONNECT_TIMEOUT_MS)
            socket.disconnectFromServer()
            return True
        logger.warning(
            "IPC connection to the running instance failed (attempt %s/%s): %s",
            attempt,
            IPC_CONNECT_ATTEMPTS,
            socket.errorString(),
        )
    return False


def main() -> int:
    """アプリを起動する。新規起動なら QApplication を実行し、終了コードを返す。"""
    # GUI/PyInstaller 実行でも IPC 失敗等の痕跡を残せるよう、早い段階でログを初期化する
    setup_logging()
    logger.info("starting hiyoko-viewer (pid=%s, argv=%s)", os.getpid(), sys.argv[1:])

    # QLocalSocket/QSharedMemory などのイベントループ依存オブジェクトより先に
    # QApplication を生成しておく（Qt の要求。未生成のまま待機系 API を呼ぶと
    # ログオン直後などにハングすることがある）
    app = QApplication(sys.argv)

    # --- 二重起動防止とインスタンス間通信 ---
    shared_memory = QSharedMemory(APP_UNIQUE_KEY)

    # 以前のインスタンスが異常終了して取り残された共有メモリを掃除する。
    # （Unix系では segment が残ると二度と起動できなくなる。Windowsは自動解放されるため通常no-op）
    if shared_memory.attach():
        shared_memory.detach()

    # create() が False を返す = すでにメモリが確保されている = 他のインスタンスが実行中
    if not shared_memory.create(1):
        logger.info("another instance is running; forwarding args")
        if _forward_to_running_instance():
            # このインスタンスは役目を終えたので終了
            return 0
        # 既存インスタンスに届かない＝ユーザーから見て操作不能。ここで終了すると
        # 「起動しても無反応」になるので、共有メモリを持たないまま通常起動して
        # 少なくともウィンドウは出せるようにする。
        logger.warning("could not reach the running instance; starting a new window instead")

    # --- ここから下は、最初のインスタンスのみが実行する ---
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
        # 引数なし起動（exe をダブルクリック等）では 0 バイト送信になり readyRead が
        # 発火しない。ここで return してしまうと「起動しても何も起きない」ため、
        # 受信の成否によらず必ずウィンドウを前面に出す。
        if socket.waitForReadyRead(500):
            data = socket.readAll().data().decode("utf-8")
            file_paths = [p for p in data.splitlines() if p]
            if file_paths:
                viewer.load_image_from_path(file_paths[0])
        viewer.show_window()

    local_server.newConnection.connect(handle_new_connection)
    # 異常終了で取り残されたソケット（主にUnix系）を掃除してから listen する
    QLocalServer.removeServer(APP_UNIQUE_KEY)
    if not local_server.listen(APP_UNIQUE_KEY):
        # listen できないと2個目以降の起動からファイルを受け取れない（致命ではないので続行）
        logger.warning("failed to listen IPC server: %s", local_server.errorString())

    # 最初の起動時の引数を処理
    if len(sys.argv) > 1:
        initial_file_path = sys.argv[1]
        viewer.load_image_from_path(initial_file_path)

    viewer.show()

    def cleanup_on_quit():
        # ウィンドウ状態の保存はワーカー停止より先に行う。
        # （後段の wait が万一固まっても設定だけは確実に残す）
        viewer._save_settings()
        viewer.stop_movie()

        viewer.worker_thread.quit()
        # 画像ロード中などで終わらない場合に GUI が終了不能になるのを避けるためタイムアウトを付ける
        if not viewer.worker_thread.wait(3000):
            current_file = (
                viewer.image_files[viewer.current_index]
                if 0 <= viewer.current_index < len(viewer.image_files)
                else None
            )
            logger.warning(
                "worker thread did not finish in time; terminating; current_index=%s current_file=%s",
                getattr(viewer, "current_index", None),
                current_file,
            )
            # terminate は任意地点で worker を停止するため deleteLater が走らない可能性がある（終了時の最終保険）
            viewer.worker_thread.terminate()
            viewer.worker_thread.wait(1000)

        # 共有メモリを解放する
        shared_memory.detach()

    app.aboutToQuit.connect(cleanup_on_quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
