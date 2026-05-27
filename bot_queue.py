"""
Bot Response Queue: 管理机器人响应队列
避免多个机器人同时回应造成的混乱
"""

import asyncio
from typing import Dict, Callable, Optional
from dataclasses import dataclass


@dataclass
class BotResponse:
    """机器人响应任务"""
    room_id: str
    bot_name: str
    user_id: str
    user_text: str
    priority: int = 0  # 优先级：0-低，1-中，2-高
    handler: Optional[Callable] = None  # 每个响应携带自己的处理函数

    def __lt__(self, other):
        # 用于优先级队列排序
        return self.priority > other.priority  # 反向排序（高优先级先）


class BotResponseQueue:
    """
    机器人响应队列管理器：
    - 按room维护独立的响应队列
    - 避免同一room内多个机器人同时说话
    - 支持优先级
    """

    def __init__(self, max_concurrent_per_room: int = 1):
        """
        Args:
            max_concurrent_per_room: 每个room最多同时处理多少个机器人响应
        """
        self.max_concurrent_per_room = max_concurrent_per_room
        
        # room_id -> Queue[BotResponse]
        self.queues: Dict[str, asyncio.PriorityQueue] = {}
        
        # room_id -> 正在处理的任务数
        self.processing_count: Dict[str, int] = {}
        
        # 处理函数
        self.handler: Optional[Callable] = None
        
        # room_id -> 处理任务
        self.processing_tasks: Dict[str, asyncio.Task] = {}

    def set_handler(self, handler: Callable):
        """设置响应处理函数"""
        self.handler = handler

    def _get_queue(self, room_id: str) -> asyncio.PriorityQueue:
        """获取或创建room的队列"""
        if room_id not in self.queues:
            self.queues[room_id] = asyncio.PriorityQueue()
            self.processing_count[room_id] = 0
        return self.queues[room_id]

    async def enqueue(self, response: BotResponse):
        """
        加入响应队列
        立即返回，不需要等待处理
        """
        queue = self._get_queue(response.room_id)
        # PriorityQueue需要可比较的对象
        await queue.put((-response.priority, response))
        print(f"📋 Bot response queued: {response.bot_name} in {response.room_id}")
        # Processor is started only via ensure_queue_processor() so Mode 1 can
        # enqueue every bot before any handler runs.

    async def _process_queue(self, room_id: str):
        """处理某个room的响应队列"""
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
                    # Use per-response handler if available, else fall back to global handler
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
        """确保room有一个活跃的处理任务"""
        if room_id not in self.processing_tasks or self.processing_tasks[room_id].done():
            self.processing_tasks[room_id] = asyncio.create_task(self._process_queue(room_id))

    def get_queue_stats(self, room_id: str) -> Dict:
        """获取队列统计信息"""
        queue = self._get_queue(room_id)
        return {
            "room_id": room_id,
            "queue_size": queue.qsize(),
            "processing_count": self.processing_count.get(room_id, 0),
            "max_concurrent": self.max_concurrent_per_room
        }

    def get_all_stats(self) -> Dict:
        """获取所有队列的统计"""
        return {
            room_id: self.get_queue_stats(room_id)
            for room_id in self.queues.keys()
        }


# 全局实例
bot_response_queue = BotResponseQueue(max_concurrent_per_room=1)
