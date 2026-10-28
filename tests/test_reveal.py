"""エクスプローラーで表示（ファイル選択付き）の起動コマンド。"""

import pytest

from hiyoko_viewer.core import reveal


def test_windows_selects_file_in_explorer(tmp_path, monkeypatch) -> None:
    image = tmp_path / "a, b.png"
    image.write_bytes(b"x")
    calls: list[object] = []
    monkeypatch.setattr(reveal.sys, "platform", "win32")
    monkeypatch.setattr(reveal.subprocess, "Popen", lambda cmd: calls.append(cmd))

    reveal.reveal_in_file_manager(str(image))

    assert calls == [f'explorer.exe /select,"{image}"']


def test_macos_uses_open_reveal(tmp_path, monkeypatch) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(b"x")
    calls: list[object] = []
    monkeypatch.setattr(reveal.sys, "platform", "darwin")
    monkeypatch.setattr(reveal.subprocess, "Popen", lambda cmd: calls.append(cmd))

    reveal.reveal_in_file_manager(str(image))

    assert calls == [["open", "-R", str(image)]]


def test_missing_file_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(reveal.subprocess, "Popen", lambda cmd: pytest.fail("should not run"))
    with pytest.raises(FileNotFoundError):
        reveal.reveal_in_file_manager(str(tmp_path / "missing.png"))
