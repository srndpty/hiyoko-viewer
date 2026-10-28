"""キーボード/マウス/ドラッグ&ドロップ等の入力イベント処理ミックスイン。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import (
    QCloseEvent,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QWheelEvent,
)


class InputEventMixin:
    """イベントの横取りとディスパッチを担うメソッド群。"""

    def eventFilter(self, source: QObject, event: QEvent) -> bool:
        """イベントを横取りし、適切なハンドラにディスパッチする"""
        if source is self.scroll_area.viewport():
            event_type = event.type()
            if event_type == QEvent.Type.Wheel:
                # QWheelEvent にキャストして型安全性を高める
                self._handle_wheel_event(event)
                return True
            elif event_type == QEvent.Type.MouseButtonPress:
                return self._handle_mouse_press_on_viewport(event)
            elif event_type == QEvent.Type.MouseMove:
                return self._handle_mouse_move_on_viewport(event)
            elif event_type == QEvent.Type.MouseButtonRelease:
                return self._handle_mouse_release_on_viewport(event)
            elif event_type == QEvent.Type.ContextMenu:
                # QScrollArea はビューポートの右クリックを自身のポリシーで処理するため、
                # customContextMenuRequested ではなくここで直接拾う
                self._show_context_menu(event.globalPos())
                return True
            elif event_type == QEvent.Type.MouseButtonDblClick:  # ダブルクリックしたら画像読み込み
                # 何も読み込まれていない場合限定
                if not self.image_files:
                    self.open_image()
                    return True  # イベントを消費
        if source is self.scroll_area and event.type() == QEvent.Type.KeyPress:
            if self._handle_key_press_on_scroll_area(event):
                return True

        return super().eventFilter(source, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """メインウィンドウが受け取るキーイベントを処理する"""
        if self.is_loading:
            event.ignore()
            return
        key = event.key()
        # 画像送り・表示切替・終了などはメニューの QAction ショートカットが処理する。
        # スペースは押している間だけパンモードになるので、アクションにはしない。
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.space_key_pressed = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not event.isAutoRepeat() and event.key() == Qt.Key.Key_Space:
            self.space_key_pressed = False
            self.is_panning = False
            self.unsetCursor()
        else:
            super().keyReleaseEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if urls := event.mimeData().urls():
            file_path = urls[0].toLocalFile()
            self.load_image_from_path(file_path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.fit_to_window:
            self.redraw_image()
        self.update_status_bar()

    def closeEvent(self, event: QCloseEvent) -> None:
        """ウィンドウを非表示にしてトレイに格納する（セッションは保持）"""
        event.ignore()
        self.hide()

    def _handle_wheel_event(self, event: QWheelEvent) -> bool:
        """ホイールイベントを処理する"""
        if self.is_loading:
            return True
        modifiers = event.modifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            self._zoom_at_cursor(event)
        else:
            self._scroll_image(event)
        return True

    def _handle_mouse_press_on_viewport(self, event: QMouseEvent) -> bool:
        """ビューポート上でのマウスクリックを処理する。処理した場合のみ True を返す"""
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.fit_to_window and self.space_key_pressed:
                self.is_panning = True
                self.pan_last_mouse_pos = event.position()
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                return True
            if self._toggle_gif_playback():
                return True
        return False

    def _handle_mouse_move_on_viewport(self, event: QMouseEvent) -> bool:
        """ビューポート上でのマウス移動を処理する"""
        if self.is_panning:
            delta = event.position() - self.pan_last_mouse_pos
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            h_bar.setValue(int(h_bar.value() - delta.x()))
            v_bar.setValue(int(v_bar.value() - delta.y()))
            self.pan_last_mouse_pos = event.position()
            return True
        return False

    def _handle_mouse_release_on_viewport(self, event: QMouseEvent) -> bool:
        """ビューポート上でのマウスボタン解放を処理する"""
        if self.is_panning and event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = False
            cursor_shape = (
                Qt.CursorShape.OpenHandCursor
                if self.space_key_pressed
                else Qt.CursorShape.ArrowCursor
            )
            self.setCursor(QCursor(cursor_shape))
            return True
        return False

    def _handle_key_press_on_scroll_area(self, event: QKeyEvent) -> bool:
        """読み込み中はスクロールエリア既定のキー処理（矢印でスクロール等）を止める。

        画像送りや削除などの操作はメニューのショートカットが処理する。
        """
        del event
        return self.is_loading
