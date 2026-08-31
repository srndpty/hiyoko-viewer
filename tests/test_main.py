import importlib
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QSharedMemory
from PyQt6.QtNetwork import QLocalSocket

from hiyoko_viewer import app as app_module


def test_app_module_can_be_imported_without_starting_application() -> None:
    module = importlib.import_module("hiyoko_viewer.app")

    assert module.ImageViewer is not None
    assert module.QApplication is not None
    assert callable(module.main)


# --------------------------------------------------------------------------
# 委譲メッセージのエンコード/デコード
# --------------------------------------------------------------------------
def test_encode_forward_message_is_never_empty_without_args() -> None:
    # 0 バイト送信は「送れたか判定できない」「受信側の readyRead が発火しない」の
    # 両方を招くため、引数なしでも必ず中身を持たせる
    payload = app_module.encode_forward_message([])

    assert payload
    assert app_module.decode_forward_message(payload) == []


def test_encode_decode_round_trip_keeps_paths() -> None:
    payload = app_module.encode_forward_message([r"C:\画像\ひよこ.png", "b.jpg"])

    assert app_module.decode_forward_message(payload) == [r"C:\画像\ひよこ.png", "b.jpg"]


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not json",
        b"\xff\xfe",
        b'{"args": "a.png"}',
        b'{"other": []}',
        b'{"args": [{"foo": 1}]}',
        b'{"args": [123]}',
        b'{"args": ["a.png", null]}',
    ],
)
def test_decode_forward_message_tolerates_broken_payloads(data: bytes) -> None:
    assert app_module.decode_forward_message(data) == []


# --------------------------------------------------------------------------
# 受信側: 引数なしでも必ずウィンドウを出す（今回の不具合の直接的な回帰テスト）
# --------------------------------------------------------------------------
def _viewer_stub() -> SimpleNamespace:
    calls: list[tuple[str, object]] = []
    viewer = SimpleNamespace(calls=calls)
    viewer.load_image_from_path = lambda path: calls.append(("load", path))
    viewer.show_window = lambda: calls.append(("show", None))
    return viewer


def test_forwarded_message_without_args_still_shows_window() -> None:
    viewer = _viewer_stub()

    app_module.make_forwarded_message_handler(viewer)(app_module.encode_forward_message([]))

    assert viewer.calls == [("show", None)]


def test_forwarded_message_with_path_loads_then_shows_window() -> None:
    viewer = _viewer_stub()

    app_module.make_forwarded_message_handler(viewer)(app_module.encode_forward_message(["a.png"]))

    assert viewer.calls == [("load", "a.png"), ("show", None)]


def test_forwarded_message_shows_window_even_when_payload_is_broken() -> None:
    viewer = _viewer_stub()

    app_module.make_forwarded_message_handler(viewer)(b"garbage")

    assert viewer.calls == [("show", None)]


# --------------------------------------------------------------------------
# 受信側: signal 駆動で GUI スレッドを block しない
# --------------------------------------------------------------------------
class _Signal:
    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self) -> None:
        for slot in list(self._slots):
            slot()


class _FakeServerSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.readyRead = _Signal()
        self.disconnected = _Signal()
        self.deleted = 0

    def bytesAvailable(self) -> int:
        return sum(len(chunk) for chunk in self._chunks)

    def readAll(self):
        return SimpleNamespace(data=lambda: self._chunks.pop(0))

    def deleteLater(self) -> None:
        self.deleted += 1


def _single_shot_recorder(monkeypatch) -> list:
    timers: list = []
    monkeypatch.setattr(
        app_module,
        "QTimer",
        SimpleNamespace(singleShot=lambda _ms, slot: timers.append(slot)),
    )
    return timers


def test_attach_forward_receiver_assembles_chunks_on_disconnect(monkeypatch) -> None:
    timers = _single_shot_recorder(monkeypatch)
    socket = _FakeServerSocket([b'{"args": ', b'["a.png"]}'])
    received: list[bytes] = []

    app_module.attach_forward_receiver(socket, received.append)
    socket.readyRead.emit()
    socket.readyRead.emit()
    socket.disconnected.emit()

    assert received == [b'{"args": ["a.png"]}']
    assert socket.deleted == 1
    # タイムアウトが後から発火しても二重処理しない
    timers[0]()
    assert received == [b'{"args": ["a.png"]}']


def test_attach_forward_receiver_falls_back_to_timeout(monkeypatch) -> None:
    timers = _single_shot_recorder(monkeypatch)
    socket = _FakeServerSocket([b"partial"])
    received: list[bytes] = []

    # 送信側が disconnect せずに死んだケース
    app_module.attach_forward_receiver(socket, received.append)
    socket.readyRead.emit()
    timers[0]()

    assert received == [b"partial"]


def test_attach_forward_receiver_drains_unread_bytes_on_disconnect(monkeypatch) -> None:
    # readyRead を経ずに disconnected が来る順序でも payload を取りこぼさない
    _single_shot_recorder(monkeypatch)
    socket = _FakeServerSocket([b'{"args": ["a.png"]}'])
    received: list[bytes] = []

    app_module.attach_forward_receiver(socket, received.append)
    socket.disconnected.emit()

    assert received == [b'{"args": ["a.png"]}']


def test_attach_forward_receiver_drains_remaining_bytes_on_timeout(monkeypatch) -> None:
    timers = _single_shot_recorder(monkeypatch)
    socket = _FakeServerSocket([b'{"args": ', b'["a.png"]}'])
    received: list[bytes] = []

    app_module.attach_forward_receiver(socket, received.append)
    socket.readyRead.emit()  # 先頭だけ読めた状態でタイムアウトに入る
    timers[0]()

    assert received == [b'{"args": ["a.png"]}']


# --------------------------------------------------------------------------
# 送信側: 書き込み完了まで確認してから True を返す
# --------------------------------------------------------------------------
class _FakeClientSocket:
    """QLocalSocket の送信側の振る舞いを再現する。

    ``waitForBytesWritten()`` は「バッファの一部が書けた」時点で True になり得るので、
    ``flush_chunk`` で小分けに書き出される状況を再現できるようにしている。
    """

    def __init__(
        self,
        *,
        connected=True,
        written=None,
        flushed=True,
        flush_chunk=None,
        disconnect_completes=True,
    ) -> None:
        self._connected = connected
        self._written = written
        self._flushed = flushed
        self._flush_chunk = flush_chunk
        self._disconnect_completes = disconnect_completes
        self._pending = 0
        self._disconnect_requested = False
        self.payload = b""
        self.aborted = 0
        self.flush_waits = 0
        self.disconnected_count = 0

    def connectToServer(self, name: str) -> None:
        self.name = name

    def waitForConnected(self, _timeout: int) -> bool:
        return self._connected

    def write(self, data: bytes) -> int:
        self.payload = data
        accepted = len(data) if self._written is None else self._written
        self._pending = accepted
        return accepted

    def bytesToWrite(self) -> int:
        return self._pending

    def waitForBytesWritten(self, _timeout: int) -> bool:
        self.flush_waits += 1
        if not self._flushed:
            return False
        self._pending -= self._flush_chunk or self._pending
        self._pending = max(0, self._pending)
        return True

    def state(self):
        if self._disconnect_requested and self._disconnect_completes:
            return QLocalSocket.LocalSocketState.UnconnectedState
        if self._disconnect_requested:
            return QLocalSocket.LocalSocketState.ClosingState
        return QLocalSocket.LocalSocketState.ConnectedState

    def waitForDisconnected(self, _timeout: int) -> bool:
        return self._disconnect_completes

    def abort(self) -> None:
        self.aborted += 1

    def disconnectFromServer(self) -> None:
        self._disconnect_requested = True
        self.disconnected_count += 1

    def errorString(self) -> str:
        return "fake error"


def _forward_with(sockets: list[_FakeClientSocket], monkeypatch) -> bool:
    monkeypatch.setattr(app_module.sys, "argv", ["hiyoko-viewer.exe"])
    return app_module._forward_to_running_instance(socket_factory=lambda: sockets.pop(0))


def test_forward_sends_non_empty_payload_and_disconnects(monkeypatch) -> None:
    socket = _FakeClientSocket()

    assert _forward_with([socket], monkeypatch) is True
    assert socket.payload
    assert socket.disconnected_count == 1


def test_forward_returns_false_on_partial_write(monkeypatch) -> None:
    sockets = [_FakeClientSocket(written=1) for _ in range(app_module.IPC_CONNECT_ATTEMPTS)]

    assert _forward_with(list(sockets), monkeypatch) is False
    assert all(s.aborted == 1 for s in sockets)


def test_forward_waits_until_all_bytes_are_written(monkeypatch) -> None:
    # waitForBytesWritten() 1回では書き切れない（5バイトずつ捌ける）状況
    socket = _FakeClientSocket(flush_chunk=5)

    assert _forward_with([socket], monkeypatch) is True
    assert socket.bytesToWrite() == 0
    # payload は 12 バイト（{"args": []}）なので 3 回待つ必要がある
    assert socket.flush_waits == 3
    assert socket.disconnected_count == 1


def test_forward_returns_false_when_flush_times_out(monkeypatch) -> None:
    sockets = [_FakeClientSocket(flushed=False) for _ in range(app_module.IPC_CONNECT_ATTEMPTS)]

    assert _forward_with(list(sockets), monkeypatch) is False
    assert all(s.aborted == 1 for s in sockets)
    assert all(s.disconnected_count == 0 for s in sockets)


def test_forward_returns_false_when_flush_stalls_midway(monkeypatch) -> None:
    # 一部だけ書けた後に停止するケース（成功扱いにしてはいけない）
    class _StallingSocket(_FakeClientSocket):
        def waitForBytesWritten(self, timeout: int) -> bool:
            if self.flush_waits >= 1:
                self.flush_waits += 1
                return False
            return super().waitForBytesWritten(timeout)

    sockets = [_StallingSocket(flush_chunk=5) for _ in range(app_module.IPC_CONNECT_ATTEMPTS)]

    assert _forward_with(list(sockets), monkeypatch) is False
    assert all(s.bytesToWrite() > 0 for s in sockets)
    assert all(s.aborted == 1 for s in sockets)


def test_forward_returns_false_when_disconnect_does_not_complete(monkeypatch) -> None:
    sockets = [
        _FakeClientSocket(disconnect_completes=False)
        for _ in range(app_module.IPC_CONNECT_ATTEMPTS)
    ]

    assert _forward_with(list(sockets), monkeypatch) is False
    assert all(s.aborted == 1 for s in sockets)


def test_forward_retries_connection_then_succeeds(monkeypatch) -> None:
    good = _FakeClientSocket()
    sockets = [_FakeClientSocket(connected=False), good]

    assert _forward_with(sockets, monkeypatch) is True
    assert good.disconnected_count == 1


def test_forward_gives_up_after_all_attempts(monkeypatch) -> None:
    sockets = [_FakeClientSocket(connected=False) for _ in range(app_module.IPC_CONNECT_ATTEMPTS)]

    assert _forward_with(list(sockets), monkeypatch) is False


# --------------------------------------------------------------------------
# 二重起動判定: create() 失敗 = 別インスタンス、ではない
# --------------------------------------------------------------------------
class _FakeSharedMemory:
    def __init__(self, created: bool, error) -> None:
        self._created = created
        self._error = error

    def create(self, _size: int) -> bool:
        return self._created

    def error(self):
        return self._error

    def errorString(self) -> str:
        return "fake shared memory error"


def test_acquire_instance_lock_acquired() -> None:
    memory = _FakeSharedMemory(True, QSharedMemory.SharedMemoryError.NoError)

    assert app_module._acquire_instance_lock(memory) == app_module.LOCK_ACQUIRED


def test_acquire_instance_lock_detects_already_running() -> None:
    memory = _FakeSharedMemory(False, QSharedMemory.SharedMemoryError.AlreadyExists)

    assert app_module._acquire_instance_lock(memory) == app_module.LOCK_ALREADY_RUNNING


@pytest.mark.parametrize(
    "error",
    [
        QSharedMemory.SharedMemoryError.PermissionDenied,
        QSharedMemory.SharedMemoryError.OutOfResources,
        QSharedMemory.SharedMemoryError.UnknownError,
    ],
)
def test_acquire_instance_lock_does_not_confuse_other_errors(error, caplog) -> None:
    memory = _FakeSharedMemory(False, error)

    with caplog.at_level("ERROR"):
        state = app_module._acquire_instance_lock(memory)

    # 別インスタンス扱いにすると「誰も応答しない委譲」に落ちるので分けること
    assert state == app_module.LOCK_UNAVAILABLE
    assert "shared memory is unavailable" in caplog.text


def test_startup_marker_reports_a_previous_run_that_never_finished(tmp_path, caplog) -> None:
    # 強制終了された前回はハング/クラッシュの痕跡を残せないので、マーカーだけが手がかり
    app_module.begin_startup_marker(tmp_path)
    with caplog.at_level("WARNING"):
        app_module.begin_startup_marker(tmp_path)
    assert "never finished starting up" in caplog.text


def test_startup_marker_is_removed_once_startup_completes(tmp_path, caplog) -> None:
    app_module.begin_startup_marker(tmp_path)
    app_module.end_startup_marker(tmp_path)
    with caplog.at_level("WARNING"):
        app_module.begin_startup_marker(tmp_path)
    assert "never finished starting up" not in caplog.text


def test_startup_marker_is_skipped_without_a_log_directory() -> None:
    # ログ用ディレクトリを用意できなくても起動は止めない
    app_module.begin_startup_marker(None)
    app_module.end_startup_marker(None)
