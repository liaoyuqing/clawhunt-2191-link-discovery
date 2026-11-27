"""Minimal dependency-free HTML tree builder used by the link discovery module.

Only the part of HTML that matters for anchor extraction is modelled: elements,
attributes, text nodes and parent links.  Malformed markup is tolerated the way a
browser would (unmatched end tags are ignored, unknown tags are kept as-is).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterator, List, Optional

VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "basefont",
        "br",
        "col",
        "embed",
        "frame",
        "hr",
        "img",
        "input",
        "isindex",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

_WS = re.compile(r"[ \t\r\n]+")


class Node:
    """An element node (``tag`` != ``#text``) or a text node (``tag == "#text"``)."""

    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag, attrs=None, text=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children: List["Node"] = []
        self.parent = parent
        self.text = text

    @property
    def is_text(self):
        return self.tag == "#text"

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    def has_attr(self, name):
        return name in self.attrs

    def classes(self):
        return [token for token in _WS.split(self.attrs.get("class", "") or "") if token]

    def iter_descendants(self) -> Iterator["Node"]:
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            yield node
            if node.children:
                stack.extend(reversed(node.children))

    def iter_elements(self) -> Iterator["Node"]:
        for node in self.iter_descendants():
            if not node.is_text:
                yield node

    def ancestors(self) -> Iterator["Node"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def text_content(self) -> str:
        if self.is_text:
            return self.text or ""
        return "".join(child.text_content() for child in self.children)

    def collapsed_text(self) -> str:
        return _WS.sub(" ", self.text_content()).strip()

    def __repr__(self):  # pragma: no cover - debugging helper
        if self.is_text:
            return "<#text %r>" % (self.text or "")[:24]
        return "<%s %s>" % (self.tag, self.attrs)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self._stack = [self.root]

    def _attrs(self, attrs):
        return {name.lower(): (value if value is not None else "") for name, value in attrs}

    def handle_starttag(self, tag, attrs):
        node = Node(tag, self._attrs(attrs), parent=self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, self._attrs(attrs), parent=self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data):
        if data:
            self._stack[-1].children.append(Node("#text", text=data, parent=self._stack[-1]))


def parse_html(text: str) -> Node:
    """Parse ``text`` into a document node; never raises on malformed markup."""
    if text is None:
        return Node("#document")
    builder = _TreeBuilder()
    try:
        builder.feed(text)
        builder.close()
    except Exception:  # html.parser is lenient, but never let a page crash discovery
        pass
    return builder.root


def find_first(root: Node, tag: str) -> Optional[Node]:
    for node in root.iter_elements():
        if node.tag == tag:
            return node
    return None

