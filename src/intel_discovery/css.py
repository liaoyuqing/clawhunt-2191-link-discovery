"""A very small CSS selector engine (subset) used for source-configured selectors.

Supported syntax
----------------
``tag``, ``*``, ``#id``, ``.class``, ``[attr]``, ``[attr=value]``, ``[attr~=value]``,
``[attr^=value]``, ``[attr$=value]``, ``[attr*=value]``, ``[attr|=value]``,
descendant (whitespace) and child (``>``) combinators, and comma separated groups.

Pseudo classes and the sibling combinators (``+``/``~``) are rejected with
``SelectorError`` so a bad source configuration fails loudly instead of silently
extracting the wrong links.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from .dom import Node


class SelectorError(ValueError):
    """Raised when a selector uses unsupported syntax or matches nothing."""


ATTR_OPS = ("~=", "^=", "$=", "*=", "|=", "=")


def _is_name_char(ch: str) -> bool:
    return ch.isalnum() or ch in "-_"


def _parse_attr(expr: str):
    expr = expr.strip()
    if not expr:
        raise SelectorError("empty attribute selector")
    op = None
    position = -1
    for candidate in ATTR_OPS:
        found = expr.find(candidate)
        if found > 0:
            op, position = candidate, found
            break
    if op is None:
        return (expr.lower(), None, None)
    name = expr[:position].strip().lower()
    value = expr[position + len(op):].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if not name:
        raise SelectorError("attribute selector without a name: " + expr)
    return (name, op, value)


def _parse_compound(text: str):
    tag = None
    ids: List[str] = []
    classes: List[str] = []
    attrs: List[Tuple[str, object, object]] = []
    index = 0
    length = len(text)
    if index < length and text[index] == "*":
        tag = "*"
        index += 1
    elif index < length and (text[index].isalpha() or text[index] == "_"):
        start = index
        while index < length and _is_name_char(text[index]):
            index += 1
        tag = text[start:index].lower()
    while index < length:
        ch = text[index]
        if ch in "#.":
            index += 1
            start = index
            while index < length and _is_name_char(text[index]):
                index += 1
            name = text[start:index]
            if not name:
                raise SelectorError("empty id/class in selector: " + text)
            (ids if ch == "#" else classes).append(name)
        elif ch == "[":
            end = text.find("]", index)
            if end < 0:
                raise SelectorError("unterminated attribute selector: " + text)
            attrs.append(_parse_attr(text[index + 1:end]))
            index = end + 1
        elif ch == ":":
            raise SelectorError("pseudo classes are not supported: " + text)
        else:
            raise SelectorError("unexpected character %r in selector: %s" % (ch, text))
    if tag is None and not ids and not classes and not attrs:
        raise SelectorError("empty compound selector")
    return (tag, tuple(ids), tuple(classes), tuple(attrs))


def _split_groups(selector: str) -> List[str]:
    groups: List[str] = []
    buffer: List[str] = []
    depth = 0
    for ch in selector:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            groups.append("".join(buffer))
            buffer = []
        else:
            buffer.append(ch)
    groups.append("".join(buffer))
    cleaned = [group.strip() for group in groups]
    if not any(cleaned):
        raise SelectorError("empty selector")
    return [group for group in cleaned if group]


def _split_parts(group: str) -> List[Tuple[object, str]]:
    """Split one complex selector into [(combinator_to_previous, compound_text)]."""
    parts: List[Tuple[object, str]] = []
    buffer: List[str] = []
    combinator = None
    depth = 0
    for ch in group:
        if ch == "[":
            depth += 1
            buffer.append(ch)
        elif ch == "]":
            depth -= 1
            buffer.append(ch)
        elif depth == 0 and ch in ">+~":
            if ch in "+~":
                raise SelectorError("sibling combinators are not supported: " + group)
            if buffer:
                parts.append((combinator, "".join(buffer).strip()))
                buffer = []
            combinator = ">"
        elif depth == 0 and ch.isspace():
            if buffer:
                parts.append((combinator, "".join(buffer).strip()))
                buffer = []
                combinator = " "
        else:
            if not buffer and parts and combinator is None:
                combinator = " "
            buffer.append(ch)
    if buffer:
        text = "".join(buffer).strip()
        if text:
            parts.append((combinator if parts else None, text))
    if not parts:
        raise SelectorError("empty selector")
    parts[0] = (None, parts[0][1])
    return parts


def _attr_matches(node: Node, name: str, op, value) -> bool:
    if name not in node.attrs:
        return False
    actual = node.attrs.get(name, "") or ""
    if op is None:
        return True
    if op == "=":
        return actual == value
    if op == "~=":
        return value in actual.split()
    if op == "^=":
        return bool(value) and actual.startswith(value)
    if op == "$=":
        return bool(value) and actual.endswith(value)
    if op == "*=":
        return bool(value) and value in actual
    if op == "|=":
        return actual == value or actual.startswith(str(value) + "-")
    raise SelectorError("unsupported attribute operator: " + str(op))


def _match_compound(node: Node, compound) -> bool:
    if node.is_text:
        return False
    tag, ids, classes, attrs = compound
    if tag and tag != "*" and node.tag != tag:
        return False
    for identifier in ids:
        if node.attrs.get("id") != identifier:
            return False
    for css_class in classes:
        if css_class not in node.classes():
            return False
    for name, op, value in attrs:
        if not _attr_matches(node, name, op, value):
            return False
    return True


def _matches(node: Node, parts: Sequence, index: int) -> bool:
    combinator, compound = parts[index]
    if not _match_compound(node, compound):
        return False
    if index == 0:
        return True
    if combinator == ">":
        parent = node.parent
        return parent is not None and _matches(parent, parts, index - 1)
    ancestor = node.parent
    while ancestor is not None:
        if _matches(ancestor, parts, index - 1):
            return True
        ancestor = ancestor.parent
    return False


def select(root: Node, selector: str) -> List[Node]:
    """Return every element under ``root`` matching ``selector``, in document order."""
    groups = []
    for group in _split_groups(selector):
        parts = [(combinator, _parse_compound(text)) for combinator, text in _split_parts(group)]
        groups.append(parts)
    matches: List[Node] = []
    for node in _iter_elements(root):
        for parts in groups:
            if _matches(node, parts, len(parts) - 1):
                matches.append(node)
                break
    return matches


def select_first(root: Node, selector: str):
    found = select(root, selector)
    return found[0] if found else None


def _iter_elements(root: Node) -> Iterable[Node]:
    if not root.is_text:
        yield root
    for node in root.iter_elements():
        yield node

