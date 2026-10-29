from agent.core.text import fix_mojibake, html_to_text, truncate


def test_html_to_text() -> None:
    html = (
        "<p>About <b>Vested</b>&nbsp;Inc &amp; co</p>"
        '<p>URL: <a href="https://vested.co">https://vested.co</a> and '
        '<a href="https://get-carrot.com/about">our site</a> '
        '<a href="mailto:x@y.com">mail</a></p>'
        "<script>var x = 1;</script><ul><li>React</li><li>Node</li></ul>"
    )
    assert html_to_text(html) == (
        "About Vested Inc & co\n\n"
        "URL: https://vested.co and our site (https://get-carrot.com/about) mail\n\n"
        "React\n\nNode"
    )


def test_html_to_text_empty() -> None:
    assert html_to_text(None) == ""
    assert html_to_text("   ") == ""


def test_fix_mojibake() -> None:
    broken = "Sotheby\u00e2\u0080\u0099s \u00e2\u0080\u0094 ok"
    assert fix_mojibake(broken) == "Sotheby\u2019s \u2014 ok"
    assert fix_mojibake("Telefondienst f\u00c3\u00bcr") == "Telefondienst f\u00fcr"
    # Correct text is left alone.
    assert fix_mojibake("Caf\u00e9 \u2014 na\u00efve") == "Caf\u00e9 \u2014 na\u00efve"


def test_truncate() -> None:
    assert truncate("short", 10) == "short"
    assert truncate("a" * 20, 10) == "a" * 9 + "…"
