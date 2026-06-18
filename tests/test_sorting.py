import pytest

from hiyoko_viewer.core import sorting
from hiyoko_viewer.core.sorting import (
    _create_windows_logical_key,
    _load_windows_logical_comparer,
    natural_key,
)


def test_natural_key_sorts_numbered_names_by_numeric_value() -> None:
    paths = [r"C:\images\image10.png", r"C:\images\image2.png", r"C:\images\image1.png"]

    assert sorted(paths, key=natural_key) == [
        r"C:\images\image1.png",
        r"C:\images\image2.png",
        r"C:\images\image10.png",
    ]


def test_natural_key_is_case_insensitive() -> None:
    assert natural_key("A10.PNG") == natural_key("a10.png")


def test_natural_key_uses_basename_only() -> None:
    assert natural_key(r"C:\first\img12.png") == natural_key(r"C:\second\img12.png")


def test_windows_logical_key_uses_basename_with_injected_comparer() -> None:
    compared: list[tuple[str, str]] = []

    def comparer(left: str, right: str) -> int:
        compared.append((left, right))
        return (left > right) - (left < right)

    paths = [r"C:\z\b.png", r"C:\a\a.png"]

    assert sorted(paths, key=_create_windows_logical_key(comparer)) == [
        r"C:\a\a.png",
        r"C:\z\b.png",
    ]
    assert compared == [("a.png", "b.png")]


def test_windows_logical_key_fallback_is_case_insensitive() -> None:
    paths = ["b10.png", "A2.png", "a1.png"]

    assert sorted(paths, key=_create_windows_logical_key(None)) == ["a1.png", "A2.png", "b10.png"]


def test_natural_key_keeps_leading_zero_numbers_in_numeric_order() -> None:
    # ゼロ埋めの有無が混在しても数値として比較される
    paths = ["img007.png", "img8.png", "img06.png", "img10.png"]

    assert sorted(paths, key=natural_key) == [
        "img06.png",
        "img007.png",
        "img8.png",
        "img10.png",
    ]


def test_fallback_key_is_locale_lexical_not_natural_for_differing_numbers() -> None:
    # 既知の制約: フォールバックは locale 文字列順が主キーで、natural_key は
    # 文字列が同値のときのタイブレークにしか効かない。そのため桁数の異なる数字
    # （file2 vs file10）は自然順にならず辞書順になる。Windows 実機では
    # StrCmpLogicalW が使われるためこの制約は表に出ない。
    key = _create_windows_logical_key(None)
    paths = ["File10.png", "file2.png", "FILE1.png", "file20.png"]

    # '1' < '2' の辞書順。大文字小文字は無視されるので FILE1 が先頭。
    assert sorted(paths, key=key) == ["FILE1.png", "File10.png", "file2.png", "file20.png"]


def test_load_windows_logical_comparer_returns_none_on_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(sorting.sys, "platform", "linux")

    assert _load_windows_logical_comparer() is None


@pytest.mark.skipif(not sorting.sys.platform.startswith("win"), reason="Windows 限定の経路")
def test_load_windows_logical_comparer_returns_none_when_dll_unavailable(monkeypatch) -> None:
    # Shlwapi のロード自体が失敗してもフォールバックできるよう None を返す
    class _BrokenWindll:
        @property
        def Shlwapi(self):
            raise OSError("Shlwapi をロードできない")

    monkeypatch.setattr(sorting.ctypes, "windll", _BrokenWindll())

    assert _load_windows_logical_comparer() is None
