import re
from collections.abc import Iterable
from html.parser import HTMLParser

# Tags that start a new line in rendered text.
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr",
    }
)  # fmt: skip
_SKIP_TAGS = frozenset({"script", "style", "head", "title"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._link: tuple[str, int] | None = None  # (href, index of first text part)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self._link = (
                (href, len(self.parts)) if href.startswith(("http://", "https://")) else None
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link:
            # Keep link targets (often the company's website) unless the link
            # text already shows the URL.
            href, start = self._link
            if href.rstrip("/") not in "".join(self.parts[start:]):
                self.parts.append(f" ({href})")
            self._link = None
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str | None) -> str:
    """Plain text from an HTML fragment: block tags become line breaks, link
    URLs are kept in parentheses, runs of whitespace collapse."""
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_MOJIBAKE = re.compile(r"[\xc2-\xf4][\x80-\xbf]{1,3}")


def _redecode(match: re.Match[str]) -> str:
    try:
        return match.group().encode("latin-1").decode("utf-8")
    except UnicodeDecodeError:
        return match.group()


def fix_mojibake(text: str) -> str:
    """Repair UTF-8 that was decoded as Latin-1 upstream ("â\x80\x94" -> "—").
    Runs that don't decode as UTF-8 are left alone."""
    return _MOJIBAKE.sub(_redecode, text)


def fold(text: str) -> str:
    """Lowercase, with punctuation runs turned into single spaces, so
    "Full-Stack" matches "full stack" and "Next.js" matches "next js"."""
    return re.sub(r"[^a-z0-9+#]+", " ", text.lower()).strip()


def has_phrase(text: str, phrases: Iterable[str]) -> bool:
    """Whether any phrase occurs in text, compared folded. A phrase must start
    at a word boundary: "ios" matches "iOS Developer", not "Studios"; "react"
    still matches "ReactJS"."""
    folded = fold(text)
    return any(re.search(rf"(?<![a-z0-9]){re.escape(p)}", folded) for p in map(fold, phrases) if p)


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
