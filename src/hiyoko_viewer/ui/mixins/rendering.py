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
        use_movie = False

        if ext == ".gif":
            use_movie = True
        elif ext == ".webp" and self._is_animated_webp(file_path):
            # アニメーション WebP だけ QMovie で扱う
            use_movie = True

        if use_movie:
            self.svg_renderer = None
            movie = QMovie(file_path)
            if movie.isValid():
                self.current_movie = movie
                self.current_movie.frameChanged.connect(self.on_gif_first_frame)
                self.current_movie.frameChanged.connect(self.update_gif_frame_status)
                self.image_label.setMovie(self.current_movie)
                self.current_movie.start()
            else:
                # 何らかの理由で QMovie が扱えなければ静止画フォールバック
                use_movie = False

        if not use_movie:
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

        self.setWindowTitle(
            f"[{self.current_index + 1}/{len(self.image_files)}] {os.path.basename(file_path)}"
        )
        self.is_loading = False

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
            frame_info = f"🎞️ [{self.current_movie.currentFrameNumber() + 1}/{self.current_movie.frameCount()}]"
            parts.append(f"{frame_info} {state_icon}")
        status_text = "  |  ".join(parts)
        self.statusBar().showMessage(status_text)

    def stop_movie(self) -> None:
        if self.current_movie:
            try:
                self.current_movie.frameChanged.disconnect()
            except TypeError:
                pass
            self.current_movie.stop()
            self.current_movie = None
        self.image_label.setMovie(None)

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
        if self.image_label.movie() is not self.current_movie:
            self.image_label.setMovie(self.current_movie)
        if self.current_movie and self.current_movie.state() != QMovie.MovieState.Running:
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
        if self.current_movie and self.current_movie.isValid():
            state = self.current_movie.state()
            if state == QMovie.MovieState.Running:
                self.current_movie.setPaused(True)
            elif state == QMovie.MovieState.Paused:
                self.current_movie.setPaused(False)
            self.update_status_bar()
            return True
        return False

    def _step_gif_frame(self, key: int) -> None:
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
        self.setWindowTitle(DEFAULT_TITLE)
