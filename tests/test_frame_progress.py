"""フレームゲージの塗り幅と表示条件。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

from hiyoko_viewer.ui.frame_progress import (
    BAR_HEIGHT,
    BAR_WIDTH,
    FILL_COLOR,
    TRACK_COLOR,
    FrameProgressBar,
    filled_pixel_width,
    set_frame_progress,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _render(bar: FrameProgressBar) -> QImage:
    image = QImage(bar.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    bar.render(image)
    return image


def test_filled_pixel_width_keeps_a_visible_sliver_for_a_tiny_fraction() -> None:
    assert filled_pixel_width(1, 100_000, BAR_WIDTH - 2) == 1


def test_set_frame_progress_ignores_hosts_without_a_bar() -> None:
    set_frame_progress(object(), 1, 2)


def test_frame_progress_paints_only_the_track_before_the_first_frame(qapp) -> None:
    del qapp
    bar = FrameProgressBar()
    bar.set_progress(0, 66)
    bar.set_progress(0, 66)
    image = _render(bar)
    assert image.pixelColor(BAR_WIDTH // 2, BAR_HEIGHT // 2) == QColor(TRACK_COLOR)


def test_filled_pixel_width_reaches_the_end_on_the_last_frame() -> None:
    inner = BAR_WIDTH - 2

    assert filled_pixel_width(0, 66, inner) == 0
    assert filled_pixel_width(1, 66, inner) >= 1
    assert filled_pixel_width(34, 66, inner) == round(inner * 34 / 66)
    assert filled_pixel_width(66, 66, inner) == inner
    assert filled_pixel_width(80, 66, inner) == inner


def test_frame_progress_hides_unless_there_are_multiple_frames(qapp) -> None:
    del qapp
    bar = FrameProgressBar()

    bar.set_progress(1, 1)
    assert bar.testAttribute(Qt.WidgetAttribute.WA_WState_Hidden)

    bar.set_progress(34, 66)
    assert not bar.testAttribute(Qt.WidgetAttribute.WA_WState_Hidden)
    assert bar.toolTip() == "34/66"
    assert bar.size().width() == BAR_WIDTH
    assert bar.size().height() == BAR_HEIGHT

    bar.set_progress(0, 0)
    assert bar.testAttribute(Qt.WidgetAttribute.WA_WState_Hidden)
    assert bar.toolTip() == ""


def test_frame_progress_paints_a_gapless_partial_fill(qapp) -> None:
    del qapp
    bar = FrameProgressBar()
    bar.set_progress(34, 66)
    image = _render(bar)
    filled = filled_pixel_width(34, 66, BAR_WIDTH - 2)
    mid_y = BAR_HEIGHT // 2
    fill = QColor(FILL_COLOR)
    track = QColor(TRACK_COLOR)

    # 左端の内側は塗られ、塗りの直後はトラックのまま。枠のピクセルは途切れない。
    assert image.pixelColor(1, mid_y) == fill
    assert image.pixelColor(filled, mid_y) == fill
    assert image.pixelColor(filled + 1, mid_y) == track
    assert image.pixelColor(BAR_WIDTH - 2, mid_y) == track


def test_frame_progress_paints_the_full_inner_width_on_the_last_frame(qapp) -> None:
    del qapp
    bar = FrameProgressBar()
    bar.set_progress(66, 66)
    image = _render(bar)
    fill = QColor(FILL_COLOR)
    mid_y = BAR_HEIGHT // 2

    assert image.pixelColor(1, mid_y) == fill
    assert image.pixelColor(BAR_WIDTH - 2, mid_y) == fill
