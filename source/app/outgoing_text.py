from __future__ import annotations

import re
from collections.abc import Iterable


# A page is deliberately smaller than the platform's historical ten-line limit.
# This makes a ten-line AI answer split before it becomes visually disruptive.
MAX_OUTGOING_LINES = 10
AI_MAX_OUTGOING_LINES = 9
MAX_OUTGOING_MESSAGES = 2
MAX_OUTGOING_CHARS = 720
MAX_TOTAL_CHARS = MAX_OUTGOING_CHARS * MAX_OUTGOING_MESSAGES
MAX_OUTGOING_LINE_CHARS = 180
TRUNCATION_MARK = "..."


def _clean_line(value: str) -> str:
    line = str(value or "").replace("\u3000", " ").strip()
    if not line:
        return ""
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"^```(?:[a-zA-Z0-9_-]+)?\s*", "", line)
    line = line.replace("```", "").replace("**", "").replace("__", "")
    line = re.sub(r"[ \t]{2,}", " ", line)
    line = re.sub(r"([=~*_#|])\1{2,}", r"\1", line)
    line = re.sub(r"(?:[-_]){4,}", "-", line)
    return line.strip()


def normalize_outgoing_text(text: str) -> str:
    """Normalize chat output into compact, plain text without changing its order."""
    source = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized: list[str] = []
    previous_blank = False
    for raw_line in source.split("\n"):
        line = _clean_line(raw_line)
        if not line:
            if normalized and not previous_blank:
                normalized.append("")
            previous_blank = True
            continue
        normalized.append(line)
        previous_blank = False
    while normalized and not normalized[-1]:
        normalized.pop()
    return "\n".join(normalized)


def outgoing_line_count(text: str) -> int:
    normalized = normalize_outgoing_text(text)
    return len(normalized.split("\n")) if normalized else 0


def outgoing_char_count(text: str) -> int:
    return len(normalize_outgoing_text(text))


def _split_line(line: str, limit: int = MAX_OUTGOING_LINE_CHARS) -> list[str]:
    if len(line) <= limit:
        return [line]
    pieces: list[str] = []
    remaining = line
    punctuation = "，。！？；、,!?;:：）)]】"
    while len(remaining) > limit:
        pivot = max(remaining.rfind(mark, 0, limit + 1) for mark in punctuation)
        if pivot < max(20, limit // 3):
            pivot = limit
        else:
            pivot += 1
        pieces.append(remaining[:pivot].strip())
        remaining = remaining[pivot:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _display_lines(text: str) -> list[str]:
    source_lines = normalize_outgoing_text(text).split("\n")
    lines: list[str] = []
    for line in source_lines:
        if not line:
            if lines and lines[-1]:
                lines.append("")
            continue
        lines.extend(_split_line(line))
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _append_truncation(parts: list[list[str]]) -> None:
    if not parts:
        return
    target = parts[-1]
    if not target:
        target.append(TRUNCATION_MARK)
        return
    last = target[-1]
    available = MAX_OUTGOING_CHARS - (len("\n".join(target[:-1])) + (1 if len(target) > 1 else 0))
    target[-1] = (last[: max(0, available - len(TRUNCATION_MARK))].rstrip() + TRUNCATION_MARK).strip()


def _pack_lines(lines: list[str], footer: str = "", max_lines: int = MAX_OUTGOING_LINES) -> list[str]:
    """Pack text into no more than two compact chat pages, truncating overflow."""
    parts: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    truncated = False
    for line in lines:
        line_length = len(line)
        separator = 1 if current else 0
        page_index = len(parts)
        footer_line_reserve = 1 if footer and page_index == MAX_OUTGOING_MESSAGES - 1 else 0
        footer_char_reserve = (
            len(footer) + 1 + len(TRUNCATION_MARK)
            if footer and page_index == MAX_OUTGOING_MESSAGES - 1
            else 0
        )
        exceeds_page = (
            len(current) >= max_lines - footer_line_reserve
            or current_chars + separator + line_length > MAX_OUTGOING_CHARS - footer_char_reserve
        )
        if exceeds_page:
            if current:
                parts.append(current)
            current = []
            current_chars = 0
            if len(parts) >= MAX_OUTGOING_MESSAGES:
                truncated = True
                break
        current.append(line)
        current_chars += len(line) + (1 if len(current) > 1 else 0)
    if current and len(parts) < MAX_OUTGOING_MESSAGES:
        parts.append(current)
    if truncated:
        _append_truncation(parts)
    if footer:
        if not parts:
            parts = [[footer]]
        else:
            target = parts[-1]
            footer_fits = (
                len(target) < max_lines
                and len("\n".join(target)) + (1 if target else 0) + len(footer) <= MAX_OUTGOING_CHARS
            )
            if footer_fits:
                target.append(footer)
            elif len(parts) < MAX_OUTGOING_MESSAGES:
                parts.append([footer])
    return ["\n".join(part).strip() for part in parts if "\n".join(part).strip()]


def prepare_outgoing_text_messages(text: str, *, max_lines: int = MAX_OUTGOING_LINES) -> list[str]:
    """Return at most two compact DZMM-safe text messages."""
    max_lines = max(1, min(int(max_lines), MAX_OUTGOING_LINES))
    normalized = normalize_outgoing_text(text)
    if not normalized:
        return []
    lines = _display_lines(normalized)
    footer = lines.pop() if lines and lines[-1].startswith("📊 Token：") else ""
    return _pack_lines(lines, footer, max_lines)


def prepare_outgoing_text_sequence(texts: Iterable[str]) -> list[str]:
    """Normalize a multi-part reply and enforce the two-page cap everywhere."""
    normalized = [normalize_outgoing_text(text) for text in texts]
    normalized = [text for text in normalized if text]
    if not normalized:
        return []
    if len(normalized) <= MAX_OUTGOING_MESSAGES and all(
        outgoing_line_count(text) <= MAX_OUTGOING_LINES
        and outgoing_char_count(text) <= MAX_OUTGOING_CHARS
        for text in normalized
    ):
        return normalized
    if (
        len(normalized) > 1
        and normalized[-1].startswith(("https://", "http://"))
        and "\n" not in normalized[-1]
    ):
        first = prepare_outgoing_text_messages("\n".join(normalized[:-1]))
        if len(first) >= MAX_OUTGOING_MESSAGES:
            first = first[: MAX_OUTGOING_MESSAGES - 1]
        return [*first, normalized[-1]][:MAX_OUTGOING_MESSAGES]
    return prepare_outgoing_text_messages("\n".join(normalized))
