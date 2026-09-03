from __future__ import annotations


import asyncio

from app.outgoing_text import prepare_outgoing_text_messages


class MessageSender:
    def __init__(self, adapter):
        self.adapter = adapter

    async def send(self, text: str) -> bool:
        parts = prepare_outgoing_text_messages(text)
        if not parts:
            return False
        delay = float(
            self.adapter.db.get_config().get("dzmm", {}).get("send_delay_seconds", 1.5)
            or 1.5
        )
        for index, part in enumerate(parts):
            if index:
                await asyncio.sleep(delay)
            if not await self.adapter.send_message(part):
                return False
        return True
