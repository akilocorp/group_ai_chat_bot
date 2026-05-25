"""
Cache Manager: 内存缓存 + 批量写入DB
减少频繁的磁盘I/O，提升性能
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict


class CacheManager:
    """
    缓存管理器：
    - 消息缓存（内存）
    - 批量写入策略（达到阈值或定时）
    - 上下文摘要缓存
    """

    def __init__(self, batch_size: int = 50, flush_interval: float = 30.0):
        """
        Args:
            batch_size: 达到多少条消息时触发批量写入
            flush_interval: 定时写入间隔（秒）
        """
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        
        # 消息缓存：room_id -> [message, message, ...]
        self.message_cache: Dict[str, List[Dict]] = defaultdict(list)
        
        # 上下文摘要缓存：room_id -> (summary_text, timestamp)
        self.summary_cache: Dict[str, tuple] = {}
        self.summary_ttl = 60  # 摘要缓存TTL（秒）
        
        # 统计缓存
        self.stats_cache: Dict[str, Dict] = {}
        
        # 持久化回调函数
        self.on_flush_callback = None
        
        # 启动定时flush任务
        self.flush_task = None

    def set_persist_callback(self, callback):
        """设置持久化回调函数"""
        self.on_flush_callback = callback

    async def start(self):
        """启动定时flush"""
        self.flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self):
        """停止定时flush"""
        if self.flush_task:
            self.flush_task.cancel()

    # ==================== 消息缓存 ====================

    def cache_message(self, room_id: str, sender: str, text: str) -> bool:
        """
        缓存消息
        返回: True 如果达到batch_size需要flush
        """
        message = {
            "room_id": room_id,
            "sender": sender,
            "text": text,
            "timestamp": datetime.now().isoformat()
        }
        
        self.message_cache[room_id].append(message)
        
        # 清空该room的summary缓存（有新消息）
        if room_id in self.summary_cache:
            del self.summary_cache[room_id]
        
        # 检查是否需要flush
        total_messages = sum(len(msgs) for msgs in self.message_cache.values())
        return total_messages >= self.batch_size

    def get_cached_messages(self, room_id: str) -> List[Dict]:
        """获取room的缓存消息"""
        return self.message_cache.get(room_id, [])

    async def flush_messages(self, room_id: Optional[str] = None) -> int:
        """
        刷新消息到DB
        Args:
            room_id: 指定room，None时刷新所有room
        
        Returns:
            刷新的消息数
        """
        if self.on_flush_callback is None:
            return 0
        
        flushed_count = 0
        
        if room_id:
            # 只刷新指定room
            if room_id in self.message_cache:
                messages = self.message_cache[room_id]
                if messages:
                    await self.on_flush_callback("messages", messages)
                    flushed_count = len(messages)
                    self.message_cache[room_id] = []
        else:
            # 刷新所有room
            for rid, messages in list(self.message_cache.items()):
                if messages:
                    await self.on_flush_callback("messages", messages)
                    flushed_count += len(messages)
                    self.message_cache[rid] = []
        
        if flushed_count > 0:
            print(f"✅ Flushed {flushed_count} messages to DB")
        
        return flushed_count

    # ==================== 上下文摘要缓存 ====================

    def cache_summary(self, room_id: str, summary: str):
        """缓存上下文摘要"""
        self.summary_cache[room_id] = (summary, datetime.now())

    def get_cached_summary(self, room_id: str) -> Optional[str]:
        """
        获取缓存的摘要
        如果超过TTL则返回None
        """
        if room_id not in self.summary_cache:
            return None
        
        summary, timestamp = self.summary_cache[room_id]
        age = (datetime.now() - timestamp).total_seconds()
        
        if age < self.summary_ttl:
            return summary
        else:
            del self.summary_cache[room_id]
            return None

    def invalidate_summary(self, room_id: str):
        """清除特定room的摘要缓存"""
        if room_id in self.summary_cache:
            del self.summary_cache[room_id]

    # ==================== 统计缓存 ====================

    def cache_stats(self, key: str, value: Dict):
        """缓存统计数据"""
        self.stats_cache[key] = value

    def get_cached_stats(self, key: str) -> Optional[Dict]:
        """获取缓存的统计数据"""
        return self.stats_cache.get(key)

    # ==================== 定时flush ====================

    async def _periodic_flush(self):
        """定时刷新所有缓存消息"""
        try:
            while True:
                await asyncio.sleep(self.flush_interval)
                
                # 检查是否有消息需要刷新
                total_messages = sum(len(msgs) for msgs in self.message_cache.values())
                if total_messages > 0:
                    await self.flush_messages()
        except asyncio.CancelledError:
            # 停止前刷新一次
            await self.flush_messages()

    # ==================== 状态查询 ====================

    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        total_cached_messages = sum(len(msgs) for msgs in self.message_cache.values())
        cached_summaries = len(self.summary_cache)
        
        return {
            "cached_messages": total_cached_messages,
            "cached_summaries": cached_summaries,
            "batch_size_threshold": self.batch_size,
            "rooms_with_cache": list(self.message_cache.keys())
        }

    def clear_all_caches(self):
        """清除所有缓存"""
        self.message_cache.clear()
        self.summary_cache.clear()
        self.stats_cache.clear()
        print("✅ All caches cleared")


# 全局实例
cache_manager = CacheManager(batch_size=50, flush_interval=30.0)
