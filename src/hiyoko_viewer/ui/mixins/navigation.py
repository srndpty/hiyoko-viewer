"""ファイルリストの読み込み・ナビゲーション・仕分け/削除を担うミックスイン。"""

from __future__ import annotations

import logging
import os
import random
import shutil

from PyQt6.QtCore import pyqtSlot
from send2trash import send2trash

from ...core.sorting import windows_logical_key

logger = logging.getLogger(__name__)


class NavigationMixin:
    """画像リストの遷移とファイル操作のメソッド群。"""

    def load_image_from_path(self, file_path: str) -> None:
        """ファイルリストの生成をワーカーに依頼する（非同期）"""
        if not file_path:
            return

        self._clear_display()
        self._load_generation += 1
        generation = self._load_generation
        directory = os.path.dirname(file_path)
        normalized_path = os.path.normcase(os.path.normpath(file_path))
        self.request_load_list.emit(generation, directory, normalized_path)

    @pyqtSlot(int, list, int)
    def on_file_list_loaded(self, generation: int, image_list: list, initial_index: int) -> None:
        """ワーカーからのファイルリスト読み込み完了通知を受け取る"""
        if generation != self._load_generation:
            return
        if not image_list:
            self.image_label.setText("画像の読み込みに失敗しました。")
            return

        # 念のため initial_index 範囲チェック
        if not (0 <= initial_index < len(image_list)):
            initial_index = 0

        # ワーカーが「最初に開いたファイル」として渡してきたパス
        selected_path = image_list[initial_index]

        # ★ ここで Windows 論理順（StrCmpLogicalW ベース）でソート
        self.sorted_image_files = sorted(image_list, key=windows_logical_key)
        self.image_files = list(self.sorted_image_files)
        self.is_shuffled = False

        # ソート後リスト中で selected_path がどこに来たかを探しなおす
        try:
            self.current_index = self.image_files.index(selected_path)
        except ValueError:
            # 万が一見つからなければ先頭にフォールバック
            self.current_index = 0

        # ファイルリストの準備ができたので、次に画像の読み込みを開始
        self.load_image_by_index()

    def load_image_by_index(self) -> None:
        """現在のインデックスに基づいて画像を非同期で読み込む"""
        if self.is_loading or not (0 <= self.current_index < len(self.image_files)):
            return
        self.fit_to_window = True
        self.scale_factor = 1.0
        self.is_loading = True
        file_path = self.image_files[self.current_index]
        try:
            self.current_filesize = os.path.getsize(file_path)
        except OSError:
            self.current_filesize = 0
        self.setWindowTitle(f"{self.windowTitle()} | 読み込み中...")
        self.statusBar().showMessage("読み込み中...")
        self.request_load_image.emit(self._load_generation, file_path)

    def show_next_image(self) -> None:
        if self.is_loading or not self.image_files:
            return
        self.current_index = (self.current_index + 1) % len(self.image_files)
        self.load_image_by_index()

    def show_prev_image(self) -> None:
        if self.is_loading or not self.image_files:
            return
        self.current_index = (self.current_index - 1 + len(self.image_files)) % len(
            self.image_files
        )
        self.load_image_by_index()

    def _remove_path_from_lists(self, path: str) -> None:
        """image_files と sorted_image_files の両方から指定パスを削除する"""
        self.image_files = [p for p in self.image_files if p != path]
        self.sorted_image_files = [p for p in self.sorted_image_files if p != path]

    def move_current_image_and_load_next(self, subfolder_name: str) -> None:
        if self.is_loading or not self.image_files:
            return
        source_path = self.image_files[self.current_index]
        # GIF/animated WebP 表示中は QMovie がファイルハンドルを掴んでおり、
        # Windows では掴んだまま move すると失敗するため、先に解放する。
        self._release_current_file_handles()
        dest_folder = os.path.join(os.path.dirname(source_path), subfolder_name)
        os.makedirs(dest_folder, exist_ok=True)
        try:
            shutil.move(source_path, dest_folder)
            self._remove_path_from_lists(source_path)
            if not self.image_files:
                self._clear_display()
            else:
                if self.current_index >= len(self.image_files):
                    self.current_index = 0
                self.load_image_by_index()
        except Exception:
            logger.exception("ファイルの移動に失敗: %s -> %s", source_path, dest_folder)
            self.statusBar().showMessage("エラー: ファイルの移動に失敗しました", 5000)

    def delete_current_image_and_load_next(self) -> None:
        """現在の画像をごみ箱に移動し、次の画像を読み込む（確認なし）"""
        if self.is_loading or not self.image_files:
            return
        source_path = self.image_files[self.current_index]
        # 削除でも同様に、QMovie が掴むファイルハンドルを先に解放する。
        self._release_current_file_handles()
        try:
            send2trash(source_path)
            self._remove_path_from_lists(source_path)
            if not self.image_files:
                self._clear_display()
            else:
                if self.current_index >= len(self.image_files):
                    self.current_index = 0
                self.load_image_by_index()
        except Exception:
            logger.exception("ファイルの削除に失敗: %s", source_path)
            self.statusBar().showMessage("エラー: ファイルの削除に失敗しました", 5000)

    def _toggle_shuffle_mode(self) -> None:
        if not self.image_files:
            return
        self.is_shuffled = not self.is_shuffled
        if self.is_shuffled:
            random.shuffle(self.image_files)
            self.current_index = 0
            self.load_image_by_index()
        else:
            current_path = self.image_files[self.current_index]
            self.image_files = list(self.sorted_image_files)
            self.current_index = (
                self.image_files.index(current_path) if current_path in self.image_files else 0
            )
            self.update_status_bar()
