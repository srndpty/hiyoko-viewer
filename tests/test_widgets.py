from widgets import JsonHighlighter


def test_json_highlighter_builds_rules_for_json_tokens() -> None:
    highlighter = JsonHighlighter()

    patterns = [pattern.pattern for pattern, _format in highlighter.highlighting_rules]

    assert patterns == [
        r'"[^"]*"\s*:',
        r'"[^"]*"',
        r"\b-?\d+(\.\d+)?([eE][+-]?\d+)?\b",
        r"\b(true|false)\b",
        r"\bnull\b",
    ]
