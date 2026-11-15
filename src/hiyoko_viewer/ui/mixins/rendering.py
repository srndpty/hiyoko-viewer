"""画像の描画・ラスタライズ・ステータスバー表示を担うミックスイン。

``ImageViewer`` に合成されることを前提に ``self`` の各属性
(``original_pixmap`` / ``svg_renderer`` / ``scroll_area`` など) を参照する。
"""

from __future__ import annotations

import os

from PIL import Image
from PyQt6.QtCore import QSize, Qt, pyqtSlot
from PyQt6.QtGui import QImage, QMovie, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from ...config.constants import (
    DEFAULT_TITLE,
    NOTICE_TEXT_STYLE,
    WELCOME_TEXT,
    ZOOM_IN_FACTOR,
    ZOOM_OUT_FACTOR,
)
from ..action_state import sync_action_states
from ..apng_movie import ApngMovie, is_animated_png
from ..frame_progress import set_frame_progress

# 非表示中はファイルを開かず、再表示まで静止画のままにする拡張子
_MOVIE_CANDIDATE_EXTS = frozenset({".gif", ".webp", ".png"})


def _seek_movie_frame(movie: QMovie | ApngMovie, frame: int) -> None:
    """frame まで移動する。

    QMovie は隣以外のフレームへ jumpToFrame すると、失敗した時点で NotRunning になる。
    その後のコマ送りは番号だけ進み、再生も一時停止も戻せない。だから 1 枚ずつ進める。
    ApngMovie は指定フレームへ直接飛ぶ。
    """
    if frame <= 0:
        return
    if isinstance(movie, ApngMovie):
        movie.jumpToFrame(frame)
        return
    current = movie.currentFrameNumber()
    if not isinstance(current, int) or current < 0:
        current = 0
    if frame < current:
        # 0 番への移動だけは QMovie が巻き戻しとして扱う
        if not movie.jumpToFrame(0):
            return
        landed = movie.currentFrameNumber()
        current = landed if isinstance(landed, int) and landed >= 0 else 0
    while current < frame:
        if not movie.jumpToFrame(current + 1):
            return
        landed = movie.currentFrameNumber()
        if not isinstance(landed, int) or landed <= current:
            return
        current = landed


class RenderingMixin:
    """画像表示まわりのメソッド群。"""

    def _is_animated_webp(self, file_path: str) -> bool:
        """WebP がアニメーションかどうかを Pillow で判定する"""
        if not file_path.lower().endswith(".webp"):
            return False
        try:
            with Image.open(file_path) as im:
                # Pillow の WebP サポートが有効なら is_animated/n_frames が使える
                return bool(getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1)
        except Exception:
            # 壊れたファイルなどは安全側で False
            return False

    def _is_window_visible(self) -> bool:
        """表示中なら True。ウィンドウを持たない単体テストは表示中とみなす。"""
        is_visible = getattr(self, "isVisible", None)
        if not callable(is_visible):
            return True
        return bool(is_visible())

    def _open_movie(self, file_path: str) -> bool:
        """アニメーションなら再生を始め、ファイルを掴む。静止画なら何も開かず False。"""
        ext = os.path.splitext(file_path)[1].lower()
        is_apng = ext == ".png"
        if ext == ".webp" and not RenderingMixin._is_animated_webp(self, file_path):
            return False
        if ext == ".png" and not is_animated_png(file_path):
            return False
        if ext not in (".gif", ".webp", ".png"):
            return False

        # Qt は APNG を解釈できないため、PNG のアニメーションだけ ApngMovie で扱う
        movie = ApngMovie(file_path) if is_apng else QMovie(file_path)
        if not movie.isValid():
            # 開けなくても QMovie はファイルを掴んだままになることがある
            RenderingMixin._close_movie_file(self, movie)
            return False

        self.svg_renderer = None
        self.current_movie = movie
        movie.frameChanged.connect(self.on_gif_first_frame)
        movie.frameChanged.connect(self.update_gif_frame_status)
        if is_apng:
            # QLabel は QMovie しか setMovie できないので、フレームごとに pixmap を差し替える
            movie.frameChanged.connect(self._show_apng_frame)
        else:
            self.image_label.setMovie(movie)
        movie.start()
        return True

    def _show_still_image(self, file_path: str, ext: str, image: QImage) -> None:
        """デコード済みの静止画（またはアニメーションの先頭フレーム）を表示する。"""
        # SVG はベクターのまま保持し、ズーム/フィットのたびに再ラスタライズする。
        # （worker が渡す pixmap は固有サイズの 1 回ラスタライズで、拡大するとガビガビになるため）
        self.svg_renderer = None
        if ext in (".svg", ".svgz"):
            renderer = QSvgRenderer(file_path)
            if renderer.isValid():
                self.svg_renderer = renderer

        if self.svg_renderer is not None:
            size = self.svg_renderer.defaultSize()
            if size.isEmpty():
                size = QSize(512, 512)
            # original_pixmap は固有サイズの基準（サイズ表示・アスペクト比）として保持
            self.original_pixmap = self._render_svg(size)
        elif image.isNull():
            self.image_label.setText("画像の読み込みに失敗しました")
            self.original_pixmap = QPixmap()
        else:
            # QPixmap への変換は GUI スレッドであるここで行う
            self.original_pixmap = QPixmap.fromImage(image)
        self.redraw_image()
        self.update_status_bar()

    def _remember_suspended_playback(self) -> None:
        """ファイルを離す前に、フレーム位置と一時停止かどうかを控える。

        有限ループの周回数までは戻さない。戻すのは見えているフレームと、
        再生中でなかったことだけ。
        """
        movie = self.current_movie
        frame = 0
        paused = True
        is_valid = getattr(movie, "isValid", None)
        if movie is not None and callable(is_valid) and is_valid():
            number = movie.currentFrameNumber()
            if isinstance(number, int) and number >= 0:
                frame = number
            paused = movie.state() != QMovie.MovieState.Running
        self._suspended_movie_frame = frame
        self._suspended_movie_paused = paused

    def _restore_suspended_playback(self) -> None:
        """開き直したアニメーションを、隠す前のフレームと一時停止へ戻す。"""
        frame = getattr(self, "_suspended_movie_frame", None)
        paused = bool(getattr(self, "_suspended_movie_paused", False))
        self._suspended_movie_frame = None
        self._suspended_movie_paused = False
        movie = self.current_movie
        if movie is None or not movie.isValid():
            return
        if isinstance(frame, int) and frame > 0:
            _seek_movie_frame(movie, frame)
        if paused and movie.state() == QMovie.MovieState.Running:
            movie.setPaused(True)

    def _recover_failed_movie_resume(self, file_path: str) -> None:
        """開き直せなかったアニメーションの、隠す前の画像を残さない。"""
        self._suspended_movie_frame = None
        self._suspended_movie_paused = False
        self.original_pixmap = QPixmap()
        self.svg_renderer = None
        self.stop_movie()
        set_frame_progress(self, 0, 0)
        name = os.path.basename(file_path)
        if os.path.isfile(file_path):
            self.load_image_by_index()
            return
        self.image_label.setText(f"ファイルが見つかりません\n{name}")
        self.image_label.setStyleSheet(NOTICE_TEXT_STYLE)
        self.statusBar().showMessage(f"ファイルが見つかりません: {name}", 3000)

    def _resume_suspended_movie(self) -> None:
        """トレイから戻したとき、隠す前に離したアニメーションを開き直す。"""
        if not getattr(self, "_resume_movie_on_show", False):
            return
        self._resume_movie_on_show = False
        if self.is_loading or not self.image_files or self.current_index < 0:
            return
        if self.current_movie is not None:
            return
        file_path = self.image_files[self.current_index]
        if self._open_movie(file_path):
            self.redraw_image()
            restore = getattr(self, "_restore_suspended_playback", None)
            if restore is not None:
                restore()
            self.update_status_bar()
        elif getattr(self, "_suspended_movie_frame", None) is not None:
            self._recover_failed_movie_resume(file_path)
        sync_action_states(self)

    @pyqtSlot(int, str, QImage)
    def update_image_display(self, generation: int, file_path: str, image: QImage) -> None:
        # 別ディレクトリを開き直した後に届いた古い結果は無視する
        if generation != self._load_generation:
            return
        if not self.image_files or self.current_index < 0:
            return
        if self.image_files[self.current_index] != file_path:
            return
        self.stop_movie()
        ext = os.path.splitext(file_path)[1].lower()
        # 別の画像を表示するので、前のアニメーションの一時停止位置は使わない
        self._suspended_movie_frame = None
        self._suspended_movie_paused = False
        # トレイ格納中にデコードが終わっても、アニメーション用にファイルを開き直さない
        # メソッドはクラスから呼ぶ。単体テストは SimpleNamespace を self に渡すため。
        if ext in _MOVIE_CANDIDATE_EXTS and not RenderingMixin._is_window_visible(self):
            self._resume_movie_on_show = True
            RenderingMixin._show_still_image(self, file_path, ext, image)
            displayed = not image.isNull()
        elif RenderingMixin._open_movie(self, file_path):
            self._resume_movie_on_show = False
            displayed = True
        else:
            self._resume_movie_on_show = False
            RenderingMixin._show_still_image(self, file_path, ext, image)
            displayed = self.svg_renderer is not None or not image.isNull()
        if displayed:
            commit = getattr(self, "_commit_pending_recent_file", None)
            if commit is not None:
                commit(generation, file_path)
        else:
            drop = getattr(self, "_drop_pending_recent_file", None)
            if drop is not None:
                drop(generation, file_path)

        self.setWindowTitle(
            f"[{self.current_index + 1}/{len(self.image_files)}] {os.path.basename(file_path)}"
        )
        self.is_loading = False
        sync_action_states(self)

    @pyqtSlot(int)
    def on_gif_first_frame(self, frame_number: int) -> None:
        if not self.current_movie:
            return
        first_frame_pixmap = self.current_movie.currentPixmap()
        if not first_frame_pixmap.isNull():
            self.original_pixmap = first_frame_pixmap
            try:
                self.current_movie.frameChanged.disconnect(self.on_gif_first_frame)
            except TypeError:
                pass
            self.redraw_image()
            self.update_status_bar()

    @pyqtSlot(int)
    def _show_apng_frame(self, frame_number: int) -> None:
        if isinstance(self.current_movie, ApngMovie):
            self.image_label.setPixmap(self.current_movie.currentPixmap())

    @pyqtSlot(int)
    def update_gif_frame_status(self, frame_number: int) -> None:
        if self.current_movie and self.current_movie.isValid():
            self.update_status_bar()

    def redraw_image(self) -> None:
        if self.original_pixmap.isNull():
            return
        is_gif = self.current_movie and self.current_movie.isValid()
        if is_gif:
            self._redraw_gif()
        else:
            self._redraw_static_image()

    def update_status_bar(self) -> None:
        if self.original_pixmap.isNull():
            self.statusBar().clearMessage()
            set_frame_progress(self, 0, 0)
            return
        parts: list[str] = []
        w, h = self.original_pixmap.width(), self.original_pixmap.height()
        fs_mb = f"{self.current_filesize / (1024 * 1024):.2f}MB"
        parts.append(f"🖼️ {w}x{h}")
        parts.append(f"💾 {fs_mb}")
        if self.fit_to_window:
            vp_size = self.scroll_area.viewport().size()
            scale = min(vp_size.width() / w, vp_size.height() / h) if w > 0 and h > 0 else 0
            zoom_percent = scale * 100
            mode_icon = "↕️"
        else:
            zoom_percent = self.scale_factor * 100
            mode_icon = ""
        parts.append(f"{mode_icon} {zoom_percent:.1f}%")
        if self.is_shuffled:
            parts.append("🔀")
        if self.current_movie and self.current_movie.isValid():
            state = self.current_movie.state()
            state_icon = "►" if state == QMovie.MovieState.Running else "⏸"
            frame_number = self.current_movie.currentFrameNumber() + 1
            frame_count = self.current_movie.frameCount()
            set_frame_progress(self, frame_number, frame_count, state_icon)
        else:
            set_frame_progress(self, 0, 0)
        status_text = "  |  ".join(parts)
        self.statusBar().showMessage(status_text)

    def _release_current_file_handles(self) -> None:
        """現在表示中のファイルを掴み得るリソース（QMovie / ApngMovie）を解放する。

        QMovie.stop() は Windows のファイルハンドルを閉じない。破棄か setFileName("") まで
        掴んだままになる。ApngMovie は Pillow のファイルを stop() で閉じる。
        静止画の pixmap はメモリ上にあり元ファイルを掴まない。QLabel.setMovie(None) は
        pixmap まで消すので、QMovie を載せていないときは呼ばない。
        """
        self.stop_movie()

    def _close_movie_file(self, movie: QMovie | ApngMovie) -> None:
        """再生を止め、元ファイルのハンドルをすぐに閉じる。"""
        try:
            movie.frameChanged.disconnect()
        except TypeError:
            pass
        movie.stop()
        # QMovie.stop() は QFile を閉じない。空のファイル名でデバイスを捨てる。
        if isinstance(movie, QMovie):
            movie.setFileName("")

    def stop_movie(self) -> None:
        movie = self.current_movie
        if movie is None:
            return
        self.current_movie = None
        # QLabel が QMovie を掴んでいると、Python 側の参照を捨ててもハンドルが残る。
        # setMovie(None) は pixmap も消すので、QMovie を載せていないときは呼ばない。
        if self.image_label.movie() is not None:
            self.image_label.setMovie(None)
        RenderingMixin._close_movie_file(self, movie)
        sync_action_states(self)

    def _redraw_gif(self) -> None:
        self.image_label.setScaledContents(True)
        if self.fit_to_window:
            self.scroll_area.setWidgetResizable(False)
            scaled_pixmap = self.original_pixmap.scaled(
                self.scroll_area.viewport().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setFixedSize(scaled_pixmap.size())
        else:
            self.scroll_area.setWidgetResizable(False)
            scaled_size = self.original_pixmap.size() * self.scale_factor
            self.image_label.setFixedSize(scaled_size)
        if isinstance(self.current_movie, ApngMovie):
            self.image_label.setPixmap(self.current_movie.currentPixmap())
        elif self.image_label.movie() is not self.current_movie:
            self.image_label.setMovie(self.current_movie)
        # 一時停止はリサイズでも維持する。止まっているときだけ再生を始める。
        if (
            self.current_movie is not None
            and self.current_movie.state() == QMovie.MovieState.NotRunning
        ):
            self.current_movie.start()

    def _redraw_static_image(self) -> None:
        self.image_label.setMinimumSize(1, 1)
        self.image_label.setMaximumSize(16777215, 16777215)
        self.image_label.setScaledContents(False)
        if self.fit_to_window:
            self.scroll_area.setWidgetResizable(True)
            scaled_pixmap = self._scaled_pixmap_for(self.scroll_area.viewport().size())
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.scroll_area.setWidgetResizable(False)
            bounds = QSize(
                int(self.original_pixmap.width() * self.scale_factor),
                int(self.original_pixmap.height() * self.scale_factor),
            )
            scaled_pixmap = self._scaled_pixmap_for(bounds)
            self.image_label.setPixmap(scaled_pixmap)
            self.image_label.adjustSize()

    def _scaled_pixmap_for(self, bounds: QSize) -> QPixmap:
        """bounds に収まるよう（アスペクト比維持で）スケールした pixmap を返す。

        SVG はベクターから表示サイズちょうどで都度ラスタライズするのでズームしても
        鮮明なまま。それ以外は元 pixmap を平滑補間でスケールする。
        """
        if self.svg_renderer is not None:
            return self._render_svg(self._aspect_fit_size(bounds))
        return self.original_pixmap.scaled(
            bounds.width(),
            bounds.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _aspect_fit_size(self, bounds: QSize) -> QSize:
        """original_pixmap のアスペクト比を保ったまま bounds に収まる最大サイズ。"""
        w, h = self.original_pixmap.width(), self.original_pixmap.height()
        if w <= 0 or h <= 0:
            return bounds
        scale = min(bounds.width() / w, bounds.height() / h)
        return QSize(max(1, round(w * scale)), max(1, round(h * scale)))

    def _render_svg(self, size: QSize) -> QPixmap:
        """保持中の SVG を指定ピクセルサイズでラスタライズする。"""
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.svg_renderer.render(painter)
        painter.end()
        return QPixmap.fromImage(image)

    def _toggle_fit_mode(self) -> None:
        if getattr(self, "is_loading", False):
            return
        self.fit_to_window = not self.fit_to_window
        if not self.fit_to_window:
            self.scale_factor = 1.0
        self.redraw_image()
        self.update_status_bar()

    def _zoom_at_cursor(self, event) -> None:
        old_scale_factor = self.scale_factor
        if self.fit_to_window:
            pixmap_size = self.original_pixmap.size()
            if pixmap_size.width() == 0 or pixmap_size.height() == 0:
                return
            vp_size = self.scroll_area.viewport().size()
            scale = min(
                vp_size.width() / pixmap_size.width(), vp_size.height() / pixmap_size.height()
            )
            self.scale_factor = scale
            self.fit_to_window = False
        angle_delta = event.angleDelta().y()
        self.scale_factor *= ZOOM_IN_FACTOR if angle_delta > 0 else ZOOM_OUT_FACTOR
        self.redraw_image()
        mouse_pos = event.position()
        h_bar, v_bar = self.scroll_area.horizontalScrollBar(), self.scroll_area.verticalScrollBar()
        h_scroll = (h_bar.value() + mouse_pos.x()) * (
            self.scale_factor / old_scale_factor
        ) - mouse_pos.x()
        v_scroll = (v_bar.value() + mouse_pos.y()) * (
            self.scale_factor / old_scale_factor
        ) - mouse_pos.y()
        h_bar.setValue(int(h_scroll))
        v_bar.setValue(int(v_scroll))
        self.update_status_bar()

    def _scroll_image(self, event) -> None:
        scroll_amount = event.angleDelta().y() // 120 * 40
        if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.scroll_area.horizontalScrollBar().setValue(
                self.scroll_area.horizontalScrollBar().value() - scroll_amount
            )
        else:
            self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().value() - scroll_amount
            )

    def _toggle_gif_playback(self) -> bool:
        if getattr(self, "is_loading", False):
            return False
        if self.current_movie and self.current_movie.isValid():
            state = self.current_movie.state()
            if state == QMovie.MovieState.Running:
                self.current_movie.setPaused(True)
            elif state == QMovie.MovieState.Paused:
                self.current_movie.setPaused(False)
            self.update_status_bar()
            return True
        return False

    def _step_gif_frame(self) -> None:
        if getattr(self, "is_loading", False):
            return
        if (
            self.current_movie
            and self.current_movie.isValid()
            and self.current_movie.frameCount() > 0
        ):
            current_frame = self.current_movie.currentFrameNumber()
            total_frames = self.current_movie.frameCount()
            new_frame = (current_frame + 1) % total_frames
            self.current_movie.jumpToFrame(new_frame)
            self.current_movie.setPaused(True)
            self.update_status_bar()

    def _clear_display(self) -> None:
        self.stop_movie()
        self.is_loading = False
        self.original_pixmap = QPixmap()
        self.svg_renderer = None
        self.image_label.setText(WELCOME_TEXT)
        self.image_label.setStyleSheet(NOTICE_TEXT_STYLE)
        self.current_index = -1
        self.statusBar().showMessage("")
        set_frame_progress(self, 0, 0)
        self.setWindowTitle(DEFAULT_TITLE)
        sync_action_states(self)
