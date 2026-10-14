"""アニメーションのフレーム位置を描くステータスバー用ゲージ。

1 文字を 8 分割して埋める Unicode ブロック（U+2588 █ から U+258F ▏）は、
等幅フォントの中ではセル境界まで塗れる。ステータスバーはプロポーショナルな
UI フォントなので、文字の間に隙間や別フォントへのフォールバックが出る。
ここでは 240px の矩形をピクセル単位で塗る。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget

BAR_WIDTH = 240
BAR_HEIGHT = 14
# drawRect の 1px 枠の内側
_INNER_INSET = 1

FILL_COLOR = "#F6C445"
TRACK_COLOR = "#454545"
BORDER_COLOR = "#9A9A9A"


def filled_pixel_width(current: int, total: int, inner_width: int) -> int:
    """内側幅のうち、現在フレームまでに塗るピクセル数。

    最終フレームで内幅いっぱいになる。1 フレームでも開始位置が分かるよう、
    進行が 1px 未満のときは 1px を塗る。
    """
    if total <= 0 or current <= 0 or inner_width <= 0:
        return 0
    ratio = min(1.0, current / total)
    filled = round(inner_width * ratio)
    if filled <= 0:
        return 1
    return min(filled, inner_width)


def set_frame_progress(
    host: object, current: int, total: int, state_icon: str | None = None
) -> None:
    """ゲージと、その左のフレーム表示を更新する。ウィジェットが無ければ何もしない。"""
    bar = getattr(host, "frame_progress", None)
    if bar is not None:
        bar.set_progress(current, total)
    label = getattr(host, "frame_label", None)
    if label is None:
        return
    if state_icon and total > 0:
        label.setText(f"🎞️ [{current}/{total}] {state_icon}")
        label.setVisible(True)
    else:
        label.clear()
        label.setVisible(False)


class FrameProgressBar(QWidget):
    """フレーム進行を隙間なく塗る固定幅のゲージ。総フレームが 1 以下なら隠す。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = 0
        self._total = 0
        self._shown = False
        self.setFixedSize(BAR_WIDTH, BAR_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVisible(False)

    def set_progress(self, current: int, total: int) -> None:
        current = max(0, current)
        total = max(0, total)
        should_show = total > 1
        same = current == self._current and total == self._total and should_show == self._shown
        self._current = current
        self._total = total
        self._shown = should_show
        self.setToolTip(f"{current}/{total}" if should_show else "")
        self.setVisible(should_show)
        if not same:
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        width = self.width()
        height = self.height()
        painter.setPen(QColor(BORDER_COLOR))
        painter.setBrush(QColor(TRACK_COLOR))
        painter.drawRect(0, 0, width - 1, height - 1)

        inner_width = width - (_INNER_INSET * 2)
        filled = filled_pixel_width(self._current, self._total, inner_width)
        if filled <= 0:
            return
        painter.fillRect(
            _INNER_INSET,
            _INNER_INSET,
            filled,
            height - (_INNER_INSET * 2),
            QColor(FILL_COLOR),
        )
