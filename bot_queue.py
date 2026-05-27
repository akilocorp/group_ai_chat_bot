"""
Bot response queue: serializes bot replies per room so multiple personas do not talk over each other.
"""

import asyncio
from typing import Dict, Callable, Optional
from dataclasses import dataclass


@dataclass
class BotResponse:
    """One queued bot reply task."""
    room_id: str
    bot_name: str
    user_id: str
    user_text: str
    priority: int = 0  # 0=low, 1=medium, 2=high
    handler: Optional[Callable] = None

    def __lt__(self, other):
        return self.priority > other.priority  # higher priority first


class BotResponseQueue:
    """
    Per-room response queues:
    - One active processor per room
    - Optional priority ordering
    """

    def __init__(self, max_concurrent_per_room: int = 1):
        self.max_concurrent_per_room = max_concurrent_per_room
        self.queues: Dict[str, asyncio.PriorityQueue] = {}
        self.processing_count: Dict[str, int] = {}
        self.handler: Optional[Callable] = None
        self.processing_tasks: Dict[str, asyncio.Task] = {}

    def set_handler(self, handler: Callable):
        self.handler = handler

    def _get_queue(self, room_id: str) -> asyncio.PriorityQueue:
        if room_id not in self.queues:
            self.queues[room_id] = asyncio.PriorityQueue()
            self.processing_count[room_id] = 0
        return self.queues[room_id]

    async def enqueue(self, response: BotResponse):
        queue = self._get_queue(response.room_id)
        await queue.put((-response.priority, response))
        print(f"📋 Bot response queued: {response.bot_name} in {response.room_id}")

    async def _process_queue(self, room_id: str):
        queue = self._get_queue(room_id)
        try:
            while not queue.empty():
                if self.processing_count[room_id] >= self.max_concurrent_per_room:
                    await asyncio.sleep(0.5)
                    continue
                try:
                    _, response = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self.processing_count[room_id] += 1
                print(f"🤖 Processing bot response: {response.bot_name} in {response.room_id}")
                try:
                    fn = response.handler or self.handler
                    if fn:
                        await fn(response)
                except Exception as e:
                    print(f"❌ Error processing bot response: {e}")
                finally:
                    self.processing_count[room_id] -= 1
        except Exception as e:
            print(f"❌ Error in queue processor: {e}")

    async def ensure_queue_processor(self, room_id: str):
        if room_id not in self.processing_tasks or self.processing_tasks[room_id].done():
            self.processing_tasks[room_id] = asyncio.create_task(self._process_queue(room_id))

    def get_queue_stats(self, room_id: str) -> Dict:
        queue = self._get_queue(room_id)
        return {
            "room_id": room_id,
            "queue_size": queue.qsize(),
            "processing_count": self.processing_count.get(room_id, 0),
            "max_concurrent": self.max_concurrent_per_room,
        }

    def get_all_stats(self) -> Dict:
        return {room_id: self.get_queue_stats(room_id) for room_id in self.queues.keys()}


bot_response_queue = BotResponseQueue(max_concurrent_per_room=1)
