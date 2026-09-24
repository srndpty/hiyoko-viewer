import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QApplication

from hiyoko_viewer.ui import apng_movie
from hiyoko_viewer.ui.apng_movie import ApngMovie, is_animated_png


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


COLORS = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]


def _save_apng(path, *, loop: int = 0, default_image: bool = False) -> None:
    frames = [Image.new("RGBA", (4, 3), color) for color in COLORS]
    if default_image:
        # アニメーション外のデフォルト画像（白）を先頭に置く
        frames.insert(0, Image.new("RGBA", (4, 3), (255, 255, 255, 255)))
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=[50, 60, 70] if not default_image else [0, 50, 60, 70],
        loop=loop,
        default_image=default_image,
    )


def _pixel(movie: ApngMovie) -> tuple[int, int, int, int]:
    color = movie.currentPixmap().toImage().pixelColor(0, 0)
    return (color.red(), color.green(), color.blue(), color.alpha())


def test_is_animated_png_distinguishes_apng_and_static_png(tmp_path) -> None:
    apng = tmp_path / "anim.png"
    _save_apng(apng)
    static = tmp_path / "static.png"
    Image.new("RGBA", (4, 3)).save(static)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a png")

    assert is_animated_png(str(apng)) is True
    assert is_animated_png(str(static)) is False
    assert is_animated_png(str(broken)) is False
    assert is_animated_png(str(tmp_path / "anim.gif")) is False


def test_apng_movie_plays_frames_in_order(qapp, tmp_path) -> None:
    path = tmp_path / "anim.png"
    _save_apng(path)
    movie = ApngMovie(str(path))
    changed: list[int] = []
    movie.frameChanged.connect(changed.append)

    assert movie.isValid() is True
    assert movie.frameCount() == 3

    movie.start()
    assert movie.state() == QMovie.MovieState.Running
    assert movie.currentFrameNumber() == 0
    assert _pixel(movie) == COLORS[0]
    assert movie._timer.interval() == 50

    movie._advance()
    movie._advance()
    assert _pixel(movie) == COLORS[2]
    assert movie._timer.interval() == 70
    movie._advance()  # 無限ループなので先頭に戻る
    assert changed == [0, 1, 2, 0]
    assert movie.state() == QMovie.MovieState.Running
    movie.stop()


def test_apng_movie_stops_after_loop_count(qapp, tmp_path) -> None:
    path = tmp_path / "anim.png"
    _save_apng(path, loop=1)
    movie = ApngMovie(str(path))

    movie.start()
    movie._advance()
    movie._advance()
    movie._advance()

    assert movie.state() == QMovie.MovieState.NotRunning
    assert movie.currentFrameNumber() == 2
    movie.stop()


def test_apng_movie_pause_jump_and_stop_release_file(qapp, tmp_path) -> None:
    path = tmp_path / "anim.png"
    _save_apng(path)
    movie = ApngMovie(str(path))
    movie.start()

    movie.setPaused(True)
    assert movie.state() == QMovie.MovieState.Paused
    assert movie._timer.isActive() is False
    assert movie.jumpToFrame(1) is True
    assert _pixel(movie) == COLORS[1]
    assert movie.jumpToFrame(3) is False
    movie.setPaused(False)
    assert movie.state() == QMovie.MovieState.Running

    movie.stop()
    assert movie.isValid() is False
    assert movie.state() == QMovie.MovieState.NotRunning
    # Windows でもファイルハンドルが解放され、削除できること
    path.unlink()


def test_apng_movie_skips_default_image(qapp, tmp_path) -> None:
    path = tmp_path / "anim.png"
    _save_apng(path, default_image=True)
    movie = ApngMovie(str(path))

    assert movie.frameCount() == 3
    movie.start()
    assert _pixel(movie) == COLORS[0]
    movie.stop()


def test_apng_movie_decodes_uncached_frames_when_over_budget(qapp, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(apng_movie, "FRAME_CACHE_BUDGET_BYTES", 0)
    path = tmp_path / "anim.png"
    _save_apng(path)
    movie = ApngMovie(str(path))

    movie.start()
    movie._advance()
    movie.jumpToFrame(0)  # 後方シークでも正しく合成し直せること

    assert movie._cache == {}
    assert _pixel(movie) == COLORS[0]
    movie.stop()


def test_apng_movie_is_invalid_for_unreadable_file(qapp, tmp_path) -> None:
    movie = ApngMovie(str(tmp_path / "missing.png"))

    assert movie.isValid() is False
    movie.start()
    movie.stop()
    assert movie.state() == QMovie.MovieState.NotRunning
