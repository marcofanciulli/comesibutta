from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import Callable, Iterator


_SPACE_RE = re.compile(r"\s+")


def clean_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip()


@dataclass
class Element:
    tag: str
    attrs: dict[str, str]
    parent: Element | None = None
    children: list[Element | str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    @property
    def text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text)
        return clean_text(" ".join(parts))

    @property
    def text_with_breaks(self) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag == "br":
                parts.append("\n")
            else:
                parts.append(child.text_with_breaks)
        lines = [clean_text(line) for line in "".join(parts).splitlines()]
        return "\n".join(line for line in lines if line)

    def descendants(self, include_self: bool = False) -> Iterator[Element]:
        if include_self:
            yield self
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.descendants()

    def find_all(self, predicate: Callable[[Element], bool]) -> list[Element]:
        return [element for element in self.descendants() if predicate(element)]

    def find_first(self, predicate: Callable[[Element], bool]) -> Element | None:
        return next((element for element in self.descendants() if predicate(element)), None)


class _TreeParser(HTMLParser):
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("document", {})
        self.stack = [self.root]
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, {key: value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(element)
        if tag in {"script", "style", "svg"}:
            self._ignored_depth += 1
        if tag not in self._VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.stack[-1].children.append(data)


def parse_html(source: str) -> Element:
    parser = _TreeParser()
    parser.feed(source)
    parser.close()
    return parser.root


def has_class(name: str) -> Callable[[Element], bool]:
    return lambda element: name in element.classes


def table_matrix(table: Element) -> tuple[list[str], list[list[str]]]:
    header_row = table.find_first(lambda element: element.tag == "thead")
    headers = [] if header_row is None else [
        cell.text for cell in header_row.find_all(lambda element: element.tag in {"th", "td"})
    ]
    body = table.find_first(lambda element: element.tag == "tbody")
    if body is None:
        return headers, []
    rows: list[list[str]] = []
    for row in body.find_all(lambda element: element.tag == "tr"):
        cells = [
            cell.text
            for cell in row.children
            if isinstance(cell, Element) and cell.tag in {"th", "td"}
        ]
        if cells:
            rows.append(cells)
    return headers, rows
