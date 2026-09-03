from __future__ import annotations


class MessageReader:
    def __init__(self, adapter):
        self.adapter = adapter

    async def read(self):
        return await self.adapter.read_recent_messages()
