from __future__ import annotations

import re
from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QFontDatabase,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout, QWidget


class JsonHighlighter(QSyntaxHighlighter):
    """JSONのシンタックスハイライトを行うためのクラス"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.highlighting_rules: list[tuple[re.Pattern, QTextCharFormat]] = []

        # キー ( "key": )
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#9CDCFE"))  # 明るい青
        pattern = re.compile(r'"[^"]*"\s*:')
        self.highlighting_rules.append((pattern, key_format))

        # 文字列 ( "value" )
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178"))  # オレンジ
        pattern = re.compile(r'"[^"]*"')
        self.highlighting_rules.append((pattern, string_format))

        # 数値 ( 123, 1.23 )
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#B5CEA8"))  # 緑
        pattern = re.compile(r"\b-?\d+(\.\d+)?([eE][+-]?\d+)?\b")
        self.highlighting_rules.append((pattern, number_format))

        # 真偽値 ( true, false )
        boolean_format = QTextCharFormat()
        boolean_format.setForeground(QColor("#569CD6"))  # 青
        boolean_format.setFontWeight(QFont.Weight.Bold)
        pattern = re.compile(r"\b(true|false)\b")
        self.highlighting_rules.append((pattern, boolean_format))

        # null
        null_format = QTextCharFormat()
        null_format.setForeground(QColor("#569CD6"))  # 青
        null_format.setFontWeight(QFont.Weight.Bold)
        pattern = re.compile(r"\bnull\b")
        self.highlighting_rules.append((pattern, null_format))

    def highlightBlock(self, text: str) -> None:
        """テキストの各ブロック（行）にハイライトを適用する"""
        for pattern, format in self.highlighting_rules:
            # finditerを使って、行内の一致するすべての箇所を検索
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, format)


class MetadataDialog(QDialog):
    """メタデータを表示するためのカスタムダイアログ"""

    def __init__(
        self,
        title: str,
        content: str,
        parent: QWidget | None = None,
        strip_handler: Callable[[], None] | None = None,
        strip_disabled_reason: str | None = None,
    ) -> None:
        """strip_handler は「メタデータを削除」ボタンで呼ばれる。処理はバックグラウンドで行い、
        呼び出し側が set_busy() / set_content() でダイアログを更新する。
        None を渡すと削除ボタンを表示しない。strip_disabled_reason を渡すとボタンを無効にする。
        """
        super().__init__(parent)
        self._strip_handler = strip_handler
        self._busy = False

        self.setWindowTitle(title)
        self.content_text = content  # コピー機能のためにコンテンツを保持

        # メインレイアウト
        layout = QVBoxLayout(self)

        # スクロール可能なテキストエリア
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self.content_text)
        self.text_edit.setReadOnly(True)
        # JSONが見やすいように等幅フォントを設定
        # 1. 優先順位順にフォントの候補リストを作成
        font_candidates = ["Cascadia Code", "Consolas", "Courier New"]

        # 2. システムで利用可能な全フォントファミリーのリストを一度だけ取得する
        available_families = QFontDatabase.families()

        # 3. 候補リストをループし、利用可能なフォントファミリーリストに含まれているかチェック
        available_font = "Courier New"  # 安全なデフォルト値
        for font_name in font_candidates:
            if font_name in available_families:
                available_font = font_name
                break  # 最初に見つかったものを使う

        # 3. 見つかったフォントを適用
        font = QFont(available_font, 10)
        self.text_edit.setFont(font)
        # シンタックスハイライターを作成し、テキストドキュメントにアタッチする
        self.highlighter = JsonHighlighter(self.text_edit.document())
        # ボタン
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        copy_button = button_box.addButton("すべてコピー", QDialogButtonBox.ButtonRole.ActionRole)
        self.strip_button = None
        if strip_handler is not None:
            self.strip_button = button_box.addButton(
                "メタデータを削除", QDialogButtonBox.ButtonRole.ActionRole
            )
            if strip_disabled_reason:
                self.strip_button.setEnabled(False)
                self.strip_button.setToolTip(strip_disabled_reason)
            self.strip_button.clicked.connect(self.strip_metadata)
        self.button_box = button_box

        # UI要素をレイアウトに追加
        layout.addWidget(self.text_edit)
        layout.addWidget(button_box)

        # シグナルとスロットを接続
        button_box.accepted.connect(self.accept)  # OKボタンでダイアログを閉じる
        copy_button.clicked.connect(self.copy_to_clipboard)

        # ダイアログの初期サイズを設定
        self.resize(700, 600)

    def set_content(self, content: str) -> None:
        self.content_text = content
        self.text_edit.setPlainText(content)

    def strip_metadata(self) -> None:
        if self._strip_handler is None or self._busy:
            return
        self._strip_handler()

    def is_busy(self) -> bool:
        return self._busy

    def set_busy(self, busy: bool) -> None:
        """削除処理中はボタンを無効にし、ダイアログを閉じられないようにする。"""
        self._busy = busy
        self.button_box.setEnabled(not busy)
        if busy:
            self.setCursor(Qt.CursorShape.WaitCursor)
        else:
            self.unsetCursor()

    def reject(self) -> None:
        # 処理中に Esc や × で閉じると、完了時の更新先が無くなるため無視する
        if self._busy:
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)

    def copy_to_clipboard(self) -> None:
        """テキストエリアの内容をクリップボードにコピーする"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.content_text)
