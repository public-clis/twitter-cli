"""Helpers for composing X Article content_state payloads."""

from __future__ import annotations

import hashlib
import re
from typing import Any


DraftBlock = dict[str, Any]
DraftEntity = dict[str, Any]
DraftContentState = dict[str, Any]

_FENCE_OPEN_RE = re.compile(r"^```[A-Za-z0-9_+-]*$")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^\s*](?:[^*]*[^\s*])?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^\s*](?:[^*]*[^\s*])?)\*(?!\*)")


def _block_key(seed: str, index: int) -> str:
    return hashlib.sha1(("%s:%d" % (seed, index)).encode("utf-8")).hexdigest()[:5]


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _plain_block(block_type: str, text: str, key: str) -> DraftBlock:
    return {
        "data": {},
        "text": text,
        "key": key,
        "type": block_type,
        "entity_ranges": [],
        "inline_style_ranges": [],
    }


def _atomic_block(entity_key: int, key: str) -> DraftBlock:
    return {
        "data": {},
        "text": " ",
        "key": key,
        "type": "atomic",
        "entity_ranges": [{"key": entity_key, "offset": 0, "length": 1}],
        "inline_style_ranges": [],
    }


def _append_entity(content_state: DraftContentState, entity_type: str, mutability: str, data: dict[str, Any]) -> int:
    entity_map = content_state["entity_map"]
    key = len(entity_map)
    entity_map.append(
        {
            "key": str(key),
            "value": {
                "data": data,
                "type": entity_type,
                "mutability": mutability,
            },
        }
    )
    return key


def _find_balanced_link_end(text: str, start: int) -> int:
    """Return index of closing ')' matching '(' at ``start - 1``, or -1."""
    depth = 1
    pos = start
    while pos < len(text):
        ch = text[pos]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return pos
        elif ch in ("\n", "\r"):
            return -1
        pos += 1
    return -1


def _strip_emphasis(text: str) -> str:
    """Strip bold/italic Markdown delimiters without harming math/spaced asterisks."""
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    return text


def _process_inline_text(text: str, content_state: DraftContentState) -> tuple[str, list[dict[str, int]]]:
    """Strip inline markup and extract Markdown links while protecting inline code and images."""
    code_spans: list[str] = []

    def _stash_code(match: re.Match[str]) -> str:
        token = "\x00CODE%d\x00" % len(code_spans)
        code_spans.append(match.group(1))
        return token

    protected = _INLINE_CODE_RE.sub(_stash_code, text)
    protected = _strip_emphasis(protected)

    ranges: list[dict[str, int]] = []
    output: list[str] = []
    cursor = 0
    pos = 0

    def _restore_code(segment: str) -> str:
        if not code_spans:
            return segment
        return re.sub(
            r"\x00CODE(\d+)\x00",
            lambda m: code_spans[int(m.group(1))],
            segment,
        )

    while pos < len(protected):
        bracket_start = protected.find("[", pos)
        if bracket_start == -1:
            break
        # Skip Markdown images `![alt](url)`
        if bracket_start > 0 and protected[bracket_start - 1] == "!":
            pos = bracket_start + 1
            continue
        bracket_end = protected.find("]", bracket_start + 1)
        if bracket_end == -1 or bracket_end + 1 >= len(protected) or protected[bracket_end + 1] != "(":
            pos = bracket_start + 1
            continue
        url_start = bracket_end + 2
        url_end = _find_balanced_link_end(protected, url_start)
        if url_end == -1:
            pos = bracket_start + 1
            continue

        raw_label = protected[bracket_start + 1:bracket_end]
        raw_url = protected[url_start:url_end].strip()
        if not raw_label or not raw_url:
            pos = url_end + 1
            continue

        output.append(_restore_code(protected[cursor:bracket_start]))
        label = _restore_code(raw_label)
        url = _restore_code(raw_url)
        offset = _utf16_len("".join(output))
        output.append(label)
        entity_key = _append_entity(content_state, "LINK", "Mutable", {"url": url})
        ranges.append({"key": entity_key, "offset": offset, "length": _utf16_len(label)})
        cursor = url_end + 1
        pos = cursor

    output.append(_restore_code(protected[cursor:]))
    return "".join(output), ranges


def article_markdown_to_content_state(markdown: str) -> DraftContentState:
    """Convert a conservative Markdown subset into X Article content_state.

    Supported block forms: paragraphs, #/##/### headings, unordered and ordered
    list items, blockquotes, horizontal rules, fenced code blocks, and inline
    Markdown links.
    """
    content_state: DraftContentState = {"blocks": [], "entity_map": []}
    lines = markdown.splitlines()
    i = 0
    block_index = 0

    while i < len(lines):
        raw = lines[i].rstrip()
        stripped = raw.strip()
        i += 1
        if not stripped:
            continue

        if _FENCE_OPEN_RE.match(stripped):
            code_lines: list[str] = []
            opening = stripped
            while i < len(lines):
                code_line = lines[i].rstrip()
                i += 1
                if code_line.strip() == "```":
                    break
                code_lines.append(code_line)
            markdown_block = opening + "\n" + "\n".join(code_lines) + "\n```"
            entity_key = _append_entity(content_state, "MARKDOWN", "Mutable", {"markdown": markdown_block})
            content_state["blocks"].append(_atomic_block(entity_key, _block_key(markdown_block, block_index)))
            block_index += 1
            continue

        if stripped == "---":
            entity_key = _append_entity(content_state, "DIVIDER", "Immutable", {})
            content_state["blocks"].append(_atomic_block(entity_key, _block_key(stripped, block_index)))
            block_index += 1
            continue

        block_type = "unstyled"
        text = stripped
        if stripped.startswith("### "):
            block_type = "header-three"
            text = stripped[4:].strip()
        elif stripped.startswith("## "):
            block_type = "header-two"
            text = stripped[3:].strip()
        elif stripped.startswith("# "):
            block_type = "header-one"
            text = stripped[2:].strip()
        elif stripped.startswith("> "):
            block_type = "blockquote"
            text = stripped[2:].strip()
        elif stripped.startswith(("- ", "* ")):
            block_type = "unordered-list-item"
            text = stripped[2:].strip()
        else:
            ordered = re.match(r"^\d+\.\s+(.+)$", stripped)
            if ordered:
                block_type = "ordered-list-item"
                text = ordered.group(1).strip()

        text, entity_ranges = _process_inline_text(text, content_state)
        block = _plain_block(block_type, text, _block_key(text, block_index))
        block["entity_ranges"] = entity_ranges
        content_state["blocks"].append(block)
        block_index += 1

    if not content_state["blocks"]:
        content_state["blocks"].append(_plain_block("unstyled", "", _block_key("", 0)))

    return content_state
