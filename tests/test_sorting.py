from image_viewer import natural_key


def test_natural_key_sorts_numbered_names_by_numeric_value() -> None:
    paths = [r"C:\images\image10.png", r"C:\images\image2.png", r"C:\images\image1.png"]

    assert sorted(paths, key=natural_key) == [
        r"C:\images\image1.png",
        r"C:\images\image2.png",
        r"C:\images\image10.png",
    ]


def test_natural_key_is_case_insensitive() -> None:
    assert natural_key("A10.PNG") == natural_key("a10.png")
