"""
Cache Manager: in-memory message cache with batched DB writes.
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict


class CacheManager:
    """
    In-memory cache:
    - Message buffer per room
    - Batch flush to DB (threshold or timer)
    - Context summary cache with TTL
    """

    def __init__(self, batch_size: int = 50, flush_interval: float = 30.0):
        """
        Args:
            batch_size: flush when total cached messages reach this count
            flush_interval: periodic flush interval in seconds
        """
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        # room_id -> [message, ...]
        self.message_cache: Dict[str, List[Dict]] = defaultdict(list)

        # room_id -> (summary_text, timestamp)
        self.summary_cache: Dict[str, tuple] = {}
        self.summary_ttl = 60  # summary cache TTL (seconds)

        self.stats_cache: Dict[str, Dict] = {}
        self.on_flush_callback = None
        self.flush_task = None

    def set_persist_callback(self, callback):
        """Register async callback invoked on flush."""
        self.on_flush_callback = callback

    async def start(self):
        """Start periodic flush loop."""
        self.flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self):
        """Stop periodic flush loop."""
        if self.flush_task:
            self.flush_task.cancel()

    # --- Message cache ---

    def cache_message(self, room_id: str, sender: str, text: str) -> bool:
        """
        Cache one message. Returns True if batch_size threshold was reached.
        """
        message = {
            "room_id": room_id,
            "sender": sender,
            "text": text,
            "timestamp": datetime.now().isoformat(),
        }

        self.message_cache[room_id].append(message)

        if room_id in self.summary_cache:
            del self.summary_cache[room_id]

        total_messages = sum(len(msgs) for msgs in self.message_cache.values())
        return total_messages >= self.batch_size

    def get_cached_messages(self, room_id: str) -> List[Dict]:
        """Return cached messages for a room."""
        return self.message_cache.get(room_id, [])

    async def flush_messages(self, room_id: Optional[str] = None) -> int:
        """
        Persist cached messages via callback.
        Args:
            room_id: flush one room, or None for all rooms
        Returns:
            number of messages flushed
        """
        if self.on_flush_callback is None:
            return 0

        flushed_count = 0

        if room_id:
            if room_id in self.message_cache:
                messages = self.message_cache[room_id]
                if messages:
                    await self.on_flush_callback("messages", messages)
                    flushed_count = len(messages)
                    self.message_cache[room_id] = []
        else:
            for rid, messages in list(self.message_cache.items()):
                if messages:
                    await self.on_flush_callback("messages", messages)
                    flushed_count += len(messages)
                    self.message_cache[rid] = []

        if flushed_count > 0:
            print(f"✅ Flushed {flushed_count} messages to DB")

        return flushed_count

    # --- Summary cache ---

    def cache_summary(self, room_id: str, summary: str):
        """Store context summary for a room."""
        self.summary_cache[room_id] = (summary, datetime.now())

    def get_cached_summary(self, room_id: str) -> Optional[str]:
        """Return cached summary if still within TTL, else None."""
        if room_id not in self.summary_cache:
            return None

        summary, timestamp = self.summary_cache[room_id]
        age = (datetime.now() - timestamp).total_seconds()

        if age < self.summary_ttl:
            return summary
        del self.summary_cache[room_id]
        return None

    def invalidate_summary(self, room_id: str):
        """Drop summary cache for a room."""
        if room_id in self.summary_cache:
            del self.summary_cache[room_id]

    # --- Stats cache ---

    def cache_stats(self, key: str, value: Dict):
        self.stats_cache[key] = value

    def get_cached_stats(self, key: str) -> Optional[Dict]:
        return self.stats_cache.get(key)

    # --- Periodic flush ---

    async def _periodic_flush(self):
        """Flush all rooms on an interval."""
        try:
            while True:
                await asyncio.sleep(self.flush_interval)
                total_messages = sum(len(msgs) for msgs in self.message_cache.values())
                if total_messages > 0:
                    await self.flush_messages()
        except asyncio.CancelledError:
            await self.flush_messages()

    # --- Introspection ---

    def get_cache_stats(self) -> Dict:
        total_cached_messages = sum(len(msgs) for msgs in self.message_cache.values())
        return {
            "cached_messages": total_cached_messages,
            "cached_summaries": len(self.summary_cache),
            "batch_size_threshold": self.batch_size,
            "rooms_with_cache": list(self.message_cache.keys()),
        }

    def clear_all_caches(self):
        self.message_cache.clear()
        self.summary_cache.clear()
        self.stats_cache.clear()
        print("✅ All caches cleared")


cache_manager = CacheManager(batch_size=50, flush_interval=30.0)
