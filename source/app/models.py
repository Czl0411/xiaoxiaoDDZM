from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChatMessage:
    message_id: str
    sender: str
    text: str
    time: str = ""
    is_self: bool = False
    raw_html: str = ""
