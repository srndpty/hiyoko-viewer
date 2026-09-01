"""アプリケーションのエントリポイント。

二重起動防止（共有メモリ）とインスタンス間通信（ローカルソケット）を行い、
最初のインスタンスのみ ``ImageViewer`` を起動する。
"""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QSharedMemory, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from .core.resources import resource_path
from .ui.main_window import ImageViewer

logger = logging.getLogger(__name__)

# アプリケーションごとにユニークなキー（二重起動防止/IPC 用）
APP_UNIQUE_KEY = "hiyoko-viewer-unique-key-for-ipc"

# 既存インスタンスへの接続リトライ（ログオン直後は相手の listen が間に合わないことがある）
IPC_CONNECT_ATTEMPTS = 3
IPC_CONNECT_TIMEOUT_MS = 1500
# 送信側が disconnect せずに死んだ場合でも受信内容を処理するための保険
IPC_RECEIVE_TIMEOUT_MS = 2000

# 起動が終わらない（＝ユーザーからは「フリーズ」に見える）ときに、どこで止まって
# いるかを残すための監視。ウィンドウ表示まで到達したら解除する。
STARTUP_WATCHDOG_SEC = 20.0

# _acquire_instance_lock の結果
LOCK_ACQUIRED = "acquired"
LOCK_ALREADY_RUNNING = "already_running"
LOCK_UNAVAILABLE = "unavailable"


def setup_logging() -> Path | None:
    """GUI/PyInstaller(--windowed) 実行では標準出力が見えないため、ファイルに残す。

    %LOCALAPPDATA%\\HiyokoViewer\\logs\\hiyoko-viewer.log（取得できなければ %TEMP%）。
    ログを置いたディレクトリを返す（用意できなければ None）。
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
        return None
    return log_dir


# --------------------------------------------------------------------------
# 「ウィンドウが出ない」を後から追うための診断
# --------------------------------------------------------------------------
# 「起動したのに何も出ない」には、固まっている場合と黙って落ちた場合があり、
# ユーザーからは区別がつかない。共有メモリもプロセス終了で消えるため、ログだけでは
# どちらか判定できない。両方を痕跡として残す。
# ※ faulthandler は書き込み先のファイルを開いたままにしておく必要があるため保持する
_diagnostic_file = None


def start_diagnostics(log_dir: Path | None, timeout: float = STARTUP_WATCHDOG_SEC) -> None:
    """クラッシュハンドラを有効にし、起動ハングの監視を開始する。

    - ``faulthandler.enable()``: ネイティブ側の致命的エラー（アクセス違反など）で
      落ちた場合にスタックを残す。無言終了と区別がつくようにするのが目的。
      ただし Windows では Qt がシェル/COM とやり取りする際の**処理済み**例外
      （RPC_E_CANTCALLOUT_ININPUTSYNCCALL など）まで書き出してしまい、本物の
      クラッシュが埋もれる。調べたいのは起動時なので、起動完了と同時に外す。
    - ``dump_traceback_later()``: ``timeout`` 秒で起動が終わらなければ全スレッドの
      スタックを書き出す。Qt/OS 側（プラットフォームプラグインの初期化、シェル未
      準備でのトレイ登録など）を待って止まっていても、待ちを発生させた Python の
      フレームはスタックに残るため、原因の切り分けにはこれが決定打になる。
    """
    global _diagnostic_file
    if log_dir is None:
        return
    try:
        # --windowed では sys.stderr が None になりうるので自前のファイルへ出す
        _diagnostic_file = (log_dir / "hiyoko-viewer-hang.log").open("a", encoding="utf-8")
    except OSError:
        logger.warning("could not open the diagnostic log; skipping crash/hang diagnostics")
        return
    print(f"--- diagnostics armed (pid={os.getpid()}) ---", file=_diagnostic_file, flush=True)
    # クラッシュ検出はプロセスが終わるまで有効にしておく（起動後に落ちる場合もある）
    faulthandler.enable(file=_diagnostic_file)
    faulthandler.dump_traceback_later(timeout, repeat=True, file=_diagnostic_file)
    sys.excepthook = _log_uncaught_exception


def _log_uncaught_exception(exc_type, exc_value, traceback) -> None:
    """GUI 実行では stderr が無く、未捕捉例外の痕跡が一切残らないため自前で記録する。"""
    logger.critical("unhandled exception", exc_info=(exc_type, exc_value, traceback))


def cancel_startup_watchdog() -> None:
    """起動を完了できたので、起動時だけの診断を解除する。"""
    global _diagnostic_file
    faulthandler.cancel_dump_traceback_later()
    faulthandler.disable()
    if _diagnostic_file is not None:
        _diagnostic_file.close()
        _diagnostic_file = None


# 起動完了までの間だけ置くマーカー。ハングでもクラッシュでもなく（＝痕跡を残せない）
# 強制終了された場合でも、「前回は起動しきれていない」という事実だけは次回に伝わる。
STARTUP_MARKER_NAME = "startup-in-progress"


def _startup_marker(log_dir: Path | None) -> Path | None:
    return None if log_dir is None else log_dir / STARTUP_MARKER_NAME


def begin_startup_marker(log_dir: Path | None) -> None:
    """前回の起動が完了していたかを記録し、今回のマーカーを置く。"""
    marker = _startup_marker(log_dir)
    if marker is None:
        return
    try:
        if marker.exists():
            logger.warning(
                "the previous run never finished starting up: %s", marker.read_text("utf-8")
            )
        marker.write_text(f"pid={os.getpid()}", encoding="utf-8")
    except OSError as error:
        # 診断用でしかないので、失敗しても起動は続ける
        logger.warning("could not update the startup marker: %s", error)


def end_startup_marker(log_dir: Path | None) -> None:
    """起動を完了できたのでマーカーを消す。"""
    marker = _startup_marker(log_dir)
    if marker is None:
        return
    try:
        marker.unlink(missing_ok=True)
    except OSError as error:
        logger.warning("could not remove the startup marker: %s", error)


# --------------------------------------------------------------------------
# インスタンス間通信（IPC）
# --------------------------------------------------------------------------
def encode_forward_message(args: list[str]) -> bytes:
    """委譲メッセージを組み立てる。

    引数なし起動（exe のダブルクリック等）でも 0 バイトにならないよう JSON で包む。
    0 バイト送信は「本当に送れたのか判定できない」「受信側の readyRead が発火しない」
    の両方を招き、実際に「起動しても何も起きない」不具合の原因になっていた。
    """
    return json.dumps({"args": list(args)}, ensure_ascii=False).encode("utf-8")


def decode_forward_message(data: bytes) -> list[str]:
    """委譲メッセージからファイルパスの一覧を取り出す。壊れていれば空リスト。"""
    if not data:
        logger.warning("received an empty IPC message")
        return []
    try:
        args = json.loads(data.decode("utf-8"))["args"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        logger.warning("received a malformed IPC message (%s bytes)", len(data))
        return []
    if not isinstance(args, list):
        logger.warning("received an IPC message with an unexpected args type: %r", type(args))
        return []
    if not all(isinstance(arg, str) for arg in args):
        # 正常なクライアントは必ず list[str] を送る。型が違えば壊れたメッセージ扱い
        logger.warning("received an IPC message with non-string args")
        return []
    return [arg for arg in args if arg]


def _forward_to_running_instance(socket_factory: Callable[[], QLocalSocket] = QLocalSocket) -> bool:
    """実行中のインスタンスにファイルパスを渡す。**送信完了まで確認して** True を返す。

    False は「既存インスタンスを検出したのに操作を渡せなかった」状態。呼び出し側は
    このプロセスを黙って終わらせてはならない（ユーザーからは「起動しても何も起き
    ない＝フリーズ」に見えるため）。
    """
    payload = encode_forward_message(sys.argv[1:])

    for attempt in range(1, IPC_CONNECT_ATTEMPTS + 1):
        socket = socket_factory()
        socket.connectToServer(APP_UNIQUE_KEY)
        if not socket.waitForConnected(IPC_CONNECT_TIMEOUT_MS):
            logger.warning(
                "IPC connect failed (attempt %s/%s): %s",
                attempt,
                IPC_CONNECT_ATTEMPTS,
                socket.errorString(),
            )
            continue

        written = socket.write(payload)
        if written != len(payload):
            logger.warning(
                "IPC write was incomplete (attempt %s/%s): %s/%s bytes: %s",
                attempt,
                IPC_CONNECT_ATTEMPTS,
                written,
                len(payload),
                socket.errorString(),
            )
            socket.abort()
            continue

        # waitForBytesWritten() は「バッファの一部が書けた」時点で True になるため、
        # 1回では payload 全体の送信完了を保証しない。bytesToWrite() が 0 になるまで待つ。
        if not _flush_socket(socket, attempt):
            socket.abort()
            continue

        # 受信側は disconnected を1メッセージの区切りとして扱うので明示的に切断し、
        # こちら側の切断処理が完了したことを確認してから成功にする。
        # ※相手のハンドラ実行完了を保証する ACK プロトコルではない（相手が受信直後に
        #   落ちても、こちらは成功として扱われうる）。
        socket.disconnectFromServer()
        if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState and (
            not socket.waitForDisconnected(IPC_CONNECT_TIMEOUT_MS)
        ):
            logger.warning(
                "IPC disconnect did not complete (attempt %s/%s): %s",
                attempt,
                IPC_CONNECT_ATTEMPTS,
                socket.errorString(),
            )
            socket.abort()
            continue

        logger.info("forwarded %s bytes to the running instance", written)
        return True

    return False


def _flush_socket(socket: QLocalSocket, attempt: int) -> bool:
    """未送信バイトが無くなるまで待つ。書き切れなければ False。"""
    while socket.bytesToWrite() > 0:
        if not socket.waitForBytesWritten(IPC_CONNECT_TIMEOUT_MS):
            logger.warning(
                "IPC payload was not flushed within %s ms (attempt %s/%s): %s bytes left: %s",
                IPC_CONNECT_TIMEOUT_MS,
                attempt,
                IPC_CONNECT_ATTEMPTS,
                socket.bytesToWrite(),
                socket.errorString(),
            )
            return False
    return True


def make_forwarded_message_handler(viewer: ImageViewer) -> Callable[[bytes], None]:
    """受信した委譲メッセージを処理するハンドラを作る。"""

    def on_forwarded_message(data: bytes) -> None:
        file_paths = decode_forward_message(data)
        logger.info("received a forward request (%s bytes, %s paths)", len(data), len(file_paths))
        if file_paths:
            viewer.load_image_from_path(file_paths[0])
        # 引数なしの再起動は「ウィンドウを出して」の意思表示。受信内容によらず前面に出す。
        # ここを受信成功時だけにすると「起動しても何も起きない」に戻るので必ず呼ぶ。
        viewer.show_window()

    return on_forwarded_message


def attach_forward_receiver(socket: QLocalSocket, on_message: Callable[[bytes], None]) -> None:
    """受信接続を signal 駆動で読み取る（GUI スレッドを block しない）。

    ``waitForReadyRead()`` を GUI スレッドで呼ぶとその間 UI が固まるため使わない。
    送信側の切断を1メッセージの区切りとして扱い、切断が来ない異常時もタイムアウトで
    必ず ``on_message`` を1回だけ呼ぶ。
    """
    chunks = bytearray()
    finished = False

    def drain() -> None:
        if socket.bytesAvailable():
            chunks.extend(bytes(socket.readAll().data()))

    def finish() -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        # readyRead を経ずに disconnected / タイムアウトへ来る順序でも取りこぼさない
        drain()
        on_message(bytes(chunks))
        socket.deleteLater()

    socket.readyRead.connect(drain)
    socket.disconnected.connect(finish)
    QTimer.singleShot(IPC_RECEIVE_TIMEOUT_MS, finish)


# --------------------------------------------------------------------------
# 二重起動の判定
# --------------------------------------------------------------------------
def _acquire_instance_lock(shared_memory: QSharedMemory) -> str:
    """共有メモリで単一インスタンスの権利を取りに行く。

    ``create()`` の失敗は「他インスタンスが実行中（AlreadyExists）」とは限らず、
    権限不足やリソース不足でも起こる。取り違えると正常起動できるはずの状況で
    「既存インスタンスへ委譲 → 誰も応答しない」に落ちるため、明示的に分類する。
    """
    if shared_memory.create(1):
        return LOCK_ACQUIRED
    error = shared_memory.error()
    if error == QSharedMemory.SharedMemoryError.AlreadyExists:
        return LOCK_ALREADY_RUNNING
    logger.error("shared memory is unavailable (error=%s): %s", error, shared_memory.errorString())
    return LOCK_UNAVAILABLE


def _notify(message: str) -> None:
    """起動を諦めた理由をユーザーに見せる。

    無言終了すると「起動しても無反応＝フリーズ」に見えるため、必ず理由を出す。
    かといってロック無しで通常起動すると、Windows では同じ pipe 名で 2 つの
    QLocalServer が listen できてしまい（どちらに配送されるか不定）、さらに
    QSettings の同時書き込み・トレイ二重化など別の競合も生む。よって
    single-instance を崩さない fail-closed とし、状況だけ提示する。
    """
    QMessageBox.warning(None, "ひよこビューア", message)


UNREACHABLE_INSTANCE_MESSAGE = (
    "ひよこビューアはすでに起動していますが、応答しません。\n"
    "タスクマネージャーで hiyoko-viewer.exe を終了してから、もう一度起動してください。"
)

LOCK_UNAVAILABLE_MESSAGE = (
    "ひよこビューアの二重起動チェックに失敗したため、起動を中止しました。\n"
    "しばらく待つか、サインインし直してからもう一度起動してください。\n"
    "詳細は %LOCALAPPDATA%\\HiyokoViewer\\logs\\hiyoko-viewer.log を参照してください。"
)


def main() -> int:
    """アプリを起動する。新規起動なら QApplication を実行し、終了コードを返す。"""
    # GUI/PyInstaller 実行でも IPC 失敗等の痕跡を残せるよう、早い段階でログを初期化する
    log_dir = setup_logging()
    logger.info("starting hiyoko-viewer (pid=%s, argv=%s)", os.getpid(), sys.argv[1:])
    start_diagnostics(log_dir)

    # QMessageBox などの GUI を委譲失敗時にも出せるよう、先に QApplication を作る
    # ※ここはプラットフォームプラグイン初期化やフォントキャッシュ構築を伴い、
    #   ログオン直後は待たされることがあるので前後にログを残す
    logger.info("creating QApplication")
    app = QApplication(sys.argv)
    logger.info("QApplication created")

    # --- 二重起動防止とインスタンス間通信 ---
    shared_memory = QSharedMemory(APP_UNIQUE_KEY)

    # 以前のインスタンスが異常終了して取り残された共有メモリを掃除する。
    # （Unix系では segment が残ると二度と起動できなくなる。Windowsは自動解放されるため通常no-op）
    if shared_memory.attach():
        shared_memory.detach()

    lock_state = _acquire_instance_lock(shared_memory)
    logger.info("single-instance lock: %s", lock_state)
    # マーカーはこのプロセスが唯一のインスタンスになる場合だけ扱う
    # （委譲して終わるインスタンスが触ると、常駐側の起動状態を上書きしてしまう）
    if lock_state == LOCK_ACQUIRED:
        begin_startup_marker(log_dir)
    if lock_state == LOCK_ALREADY_RUNNING:
        logger.info("another instance is running; forwarding args")
        if _forward_to_running_instance():
            # このインスタンスは役目を終えたので終了
            return 0
        logger.error("the running instance did not accept the request; giving up")
        _notify(UNREACHABLE_INSTANCE_MESSAGE)
        return 1
    if lock_state == LOCK_UNAVAILABLE:
        # 二重起動を判定できない状態で通常起動すると、既存インスタンスと IPC サーバ・
        # 設定・トレイを奪い合う。起動しない方を選ぶ（fail-closed）
        logger.error("could not take the single-instance lock; aborting startup")
        _notify(LOCK_UNAVAILABLE_MESSAGE)
        return 1

    # --- ここから下は、最初のインスタンスのみが実行する ---
    # app.setPalette() よりも強力なスタイルシートで、デフォルトのウィンドウ背景を上書きする
    # これにより、OSがウィンドウの「器」を作成する際のデフォルト色を制御する
    app.setStyleSheet("QMainWindow { background-color: #2d2d2d; }")
    app.setQuitOnLastWindowClosed(False)

    app_icon_path = resource_path("app_icon.ico")
    if os.path.exists(app_icon_path):
        app.setWindowIcon(QIcon(app_icon_path))

    logger.info("creating the main window")
    viewer = ImageViewer()
    logger.info("main window created")

    # 2番目のインスタンスからファイルパスを受け取るためのサーバーをセットアップ
    local_server = QLocalServer()

    on_forwarded_message = make_forwarded_message_handler(viewer)

    def handle_new_connection():
        socket = local_server.nextPendingConnection()
        if socket is None:
            logger.warning("newConnection was emitted but no pending connection was available")
            return
        attach_forward_receiver(socket, on_forwarded_message)

    local_server.newConnection.connect(handle_new_connection)
    # 異常終了で取り残されたソケット（主にUnix系）を掃除してから listen する
    QLocalServer.removeServer(APP_UNIQUE_KEY)
    if local_server.listen(APP_UNIQUE_KEY):
        logger.info("IPC server is listening on %s", APP_UNIQUE_KEY)
    else:
        # listen できないと2個目以降の起動からファイルを受け取れない（致命ではないので続行）
        logger.warning("failed to listen IPC server: %s", local_server.errorString())

    # 最初の起動時の引数を処理
    if len(sys.argv) > 1:
        initial_file_path = sys.argv[1]
        viewer.load_image_from_path(initial_file_path)

    viewer.show()
    logger.info("main window shown at %s", viewer.geometry())
    # ここまで来れば起動は完了。以降の待ちは監視対象外にする
    cancel_startup_watchdog()
    end_startup_marker(log_dir)

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
        logger.info("hiyoko-viewer exited")

    app.aboutToQuit.connect(cleanup_on_quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
