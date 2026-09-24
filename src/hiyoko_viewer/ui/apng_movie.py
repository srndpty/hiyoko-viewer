"""APNG（アニメーション PNG）を再生する QMovie 互換オブジェクト。

Qt 標準の PNG プラグインは APNG を解釈せず先頭フレームしか読めないため、
Pillow でフレームを合成（dispose/blend 処理込み）しながら QTimer で再生する。
表示側（RenderingMixin）が QMovie と同じ API で扱えるよう、使っているメソッド・
シグナル（frameChanged / state / setPaused / jumpToFrame など）だけを揃えている。
"""

from __future__ import annotations

import logging

from PIL import Image
from PyQt6.QtCore import QElapsedTimer, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QMovie, QPixmap

logger = logging.getLogger(__name__)

# 合成済みフレームをキャッシュする上限。これを超える分は毎回デコードする
# （大きな APNG は全フレーム展開で数百 MB になるため）。
FRAME_CACHE_BUDGET_BYTES = 256 * 1024 * 1024
# delay 0 や極端に短い delay で GUI スレッドを占有しないための下限
MIN_FRAME_DELAY_MS = 20


def _animation_frame_offset(image: Image.Image) -> int:
    """アニメーションに含まれないデフォルト画像がある場合、その分の 1 を返す。

    Pillow はデフォルト画像（IDAT）がアニメーション外のとき、それを frame 0 として
    n_frames に含めるため、再生対象からは除外する。
    """
    return 1 if getattr(image, "default_image", False) else 0


def is_animated_png(file_path: str) -> bool:
    """PNG が 2 フレーム以上のアニメーション（APNG）かどうかを判定する。"""
    if not file_path.lower().endswith(".png"):
        return False
    try:
        with Image.open(file_path) as im:
            n_frames = getattr(im, "n_frames", 1) - _animation_frame_offset(im)
            return bool(getattr(im, "is_animated", False) and n_frames > 1)
    except Exception:
        # 壊れたファイルなどは安全側で静止画扱い
        return False


class ApngMovie(QObject):
    """Pillow で APNG をデコードし、QMovie と同じ要領で再生する。

    元ファイルは再生中ずっと開いたまま（QMovie と同様）なので、move/delete の前には
    ``stop()`` を呼ぶこと。``stop()`` はファイルを閉じ、以後このオブジェクトは無効になる。
    """

    frameChanged = pyqtSignal(int)

    def __init__(self, file_path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._image: Image.Image | None = None
        self._frame_offset = 0
        self._frame_count = 0
        self._loop_count = 0  # 0 は無限ループ
        self._loops_done = 0
        self._current_frame = -1
        self._current_pixmap = QPixmap()
        self._current_delay = MIN_FRAME_DELAY_MS
        self._state = QMovie.MovieState.NotRunning
        self._cache: dict[int, tuple[QPixmap, int]] = {}
        self._cache_bytes = 0

        try:
            image = Image.open(file_path)
        except Exception:
            logger.exception("failed to open APNG: %s", file_path)
            return
        offset = _animation_frame_offset(image)
        frame_count = getattr(image, "n_frames", 1) - offset
        if frame_count <= 0:
            image.close()
            return
        self._image = image
        self._frame_offset = offset
        self._frame_count = frame_count
        self._loop_count = int(image.info.get("loop", 0) or 0)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        # 既定の CoarseTimer だと Windows では約 15.6ms 単位に丸められ、再生が遅くなる
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._advance)

    # --- QMovie 互換 API ------------------------------------------------------
    def isValid(self) -> bool:
        return self._image is not None and self._frame_count > 0

    def frameCount(self) -> int:
        return self._frame_count

    def currentFrameNumber(self) -> int:
        return self._current_frame

    def currentPixmap(self) -> QPixmap:
        return self._current_pixmap

    def state(self) -> QMovie.MovieState:
        return self._state

    def start(self) -> None:
        if not self.isValid() or self._state == QMovie.MovieState.Running:
            return
        if self._current_frame < 0 and not self._show_frame(0):
            return
        self._loops_done = 0
        self._state = QMovie.MovieState.Running
        self._timer.start(self._current_delay)

    def stop(self) -> None:
        """再生を止め、元ファイルとフレームキャッシュを解放する。"""
        if self._image is None:
            return
        self._timer.stop()
        self._state = QMovie.MovieState.NotRunning
        self._image.close()
        self._image = None
        self._cache.clear()
        self._cache_bytes = 0

    def setPaused(self, paused: bool) -> None:
        if paused and self._state == QMovie.MovieState.Running:
            self._timer.stop()
            self._state = QMovie.MovieState.Paused
        elif not paused and self._state == QMovie.MovieState.Paused:
            self._state = QMovie.MovieState.Running
            self._timer.start(self._current_delay)

    def jumpToFrame(self, frame_number: int) -> bool:
        if not self.isValid() or not 0 <= frame_number < self._frame_count:
            return False
        if not self._show_frame(frame_number):
            return False
        if self._state == QMovie.MovieState.Running:
            self._timer.start(self._current_delay)
        return True

    # --- 内部処理 -------------------------------------------------------------
    def _advance(self) -> None:
        # タイマーは「このフレームの表示予定時刻 + delay」に発火させる（deadline 方式）。
        # このフレームはデコードの分だけ遅れて表示されるが、次のフレームも同じだけ
        # デコードで遅れて表示されるため、実際の表示時間は delay になる。
        # delay をそのまま使うと、毎フレーム「delay + 次フレームのデコード時間」表示され、
        # デコードが重いほど再生が遅くなる。デコードが delay を超える場合は 0 になり、
        # 遅れは取り戻さずデコード速度なりに再生する（タイマーはイベント 1 回ずつなので入力は処理される）。
        elapsed = QElapsedTimer()
        elapsed.start()
        next_frame = self._current_frame + 1
        if next_frame >= self._frame_count:
            self._loops_done += 1
            if self._loop_count and self._loops_done >= self._loop_count:
                # 指定回数ループしたら最終フレームで止める（QMovie と同じ挙動）
                self._state = QMovie.MovieState.NotRunning
                return
            next_frame = 0
        if self._show_frame(next_frame) and self._state == QMovie.MovieState.Running:
            self._timer.start(max(0, self._current_delay - elapsed.elapsed()))

    def _show_frame(self, frame_number: int) -> bool:
        cached = self._cache.get(frame_number)
        if cached is None:
            try:
                cached = self._decode_frame(frame_number)
            except Exception:
                logger.exception("failed to decode APNG frame %d", frame_number)
                self._timer.stop()
                self._state = QMovie.MovieState.NotRunning
                return False
        self._current_frame = frame_number
        self._current_pixmap, self._current_delay = cached
        self.frameChanged.emit(frame_number)
        return True

    def _decode_frame(self, frame_number: int) -> tuple[QPixmap, int]:
        assert self._image is not None
        # Pillow の seek は前方へは差分合成、後方へは先頭から合成し直すので、
        # 通常再生（+1 ずつ）では 1 フレーム分のデコードで済む。
        self._image.seek(frame_number + self._frame_offset)
        rgba = self._image.convert("RGBA")
        width, height = rgba.size
        qimage = QImage(
            rgba.tobytes("raw", "RGBA"), width, height, width * 4, QImage.Format.Format_RGBA8888
        ).copy()
        delay = max(MIN_FRAME_DELAY_MS, round(self._image.info.get("duration") or 0))
        frame = (QPixmap.fromImage(qimage), delay)

        frame_bytes = width * height * 4
        if self._cache_bytes + frame_bytes <= FRAME_CACHE_BUDGET_BYTES:
            self._cache[frame_number] = frame
            self._cache_bytes += frame_bytes
        return frame
