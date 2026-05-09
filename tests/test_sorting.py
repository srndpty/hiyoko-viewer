import image_viewer
from image_viewer import _create_windows_logical_key, _load_windows_logical_comparer, natural_key


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


def test_load_windows_logical_comparer_returns_none_on_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(image_viewer.sys, "platform", "linux")

    assert _load_windows_logical_comparer() is None
