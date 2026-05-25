"""
Activity Logger: 记录所有系统活动
包括：消息、bot操作、room创建/关闭、config更改等
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum


class ActivityType(Enum):
    """Activity类型枚举"""
    # Room事件
    ROOM_CREATED = "room_created"
    ROOM_CLOSED = "room_closed"
    
    # 消息事件
    USER_MESSAGE = "user_message"
    BOT_RESPONSE = "bot_response"
    
    # Bot事件
    BOT_TRIGGERED = "bot_triggered"
    BOT_SKIPPED = "bot_skipped"
    
    # Session事件
    SESSION_STARTED = "session_started"
    SESSION_PAUSED = "session_paused"
    SESSION_CLOSED = "session_closed"
    
    # Config事件
    CONFIG_CHANGED = "config_changed"
    
    # 系统事件
    ERROR_OCCURRED = "error_occurred"
    EXPORT_REQUESTED = "export_requested"


class Activity:
    """单条Activity记录"""
    def __init__(self, activity_type: ActivityType, session_id: str, 
                 room_id: Optional[str] = None, actor: Optional[str] = None,
                 details: Optional[Dict] = None):
        self.activity_type = activity_type.value
        self.timestamp = datetime.now().isoformat()
        self.session_id = session_id
        self.room_id = room_id
        self.actor = actor  # User/Bot name
        self.details = details or {}

    def to_dict(self) -> Dict:
        return {
            "event_type": self.activity_type,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "room_id": self.room_id,
            "actor": self.actor,
            "details": self.details
        }


class ActivityLogger:
    """
    Activity日志记录器：
    - 记录所有系统事件
    - 持久化到文件
    - 按session/room查询
    """

    def __init__(self, log_dir: str = "activity_logs"):
        self.log_dir = log_dir
        self.activities: Dict[str, List[Activity]] = {}  # session_id -> [Activity, ...]
        
        os.makedirs(log_dir, exist_ok=True)
        self._load_activities_from_disk()

    # ==================== 日志记录 ====================

    def log_activity(self, activity: Activity) -> str:
        """记录Activity"""
        session_id = activity.session_id
        
        if session_id not in self.activities:
            self.activities[session_id] = []
        
        self.activities[session_id].append(activity)
        
        # 实时保存到文件
        self._save_activity_to_file(session_id, activity)
        
        return activity.timestamp

    def log_room_created(self, session_id: str, room_id: str, participant_id: str):
        """记录房间创建"""
        activity = Activity(
            ActivityType.ROOM_CREATED,
            session_id,
            room_id=room_id,
            details={"participant_id": participant_id}
        )
        self.log_activity(activity)

    def log_room_closed(self, session_id: str, room_id: str):
        """记录房间关闭"""
        activity = Activity(
            ActivityType.ROOM_CLOSED,
            session_id,
            room_id=room_id
        )
        self.log_activity(activity)

    def log_user_message(self, session_id: str, room_id: str, 
                        user_id: str, message: str):
        """记录用户消息"""
        activity = Activity(
            ActivityType.USER_MESSAGE,
            session_id,
            room_id=room_id,
            actor=user_id,
            details={"message": message[:100]}  # 只记录前100字
        )
        self.log_activity(activity)

    def log_bot_response(self, session_id: str, room_id: str, 
                        bot_name: str, response: str, mode: int = 1):
        """记录Bot响应"""
        activity = Activity(
            ActivityType.BOT_RESPONSE,
            session_id,
            room_id=room_id,
            actor=bot_name,
            details={
                "response": response[:100],
                "mode": mode,
                "length": len(response)
            }
        )
        self.log_activity(activity)

    def log_bot_triggered(self, session_id: str, room_id: str, bot_name: str):
        """记录Bot被触发"""
        activity = Activity(
            ActivityType.BOT_TRIGGERED,
            session_id,
            room_id=room_id,
            actor=bot_name
        )
        self.log_activity(activity)

    def log_bot_skipped(self, session_id: str, room_id: str, bot_name: str):
        """记录Bot跳过响应"""
        activity = Activity(
            ActivityType.BOT_SKIPPED,
            session_id,
            room_id=room_id,
            actor=bot_name,
            details={"reason": "mode_3_skip"}
        )
        self.log_activity(activity)

    def log_session_started(self, session_id: str, session_name: str):
        """记录Session开始"""
        activity = Activity(
            ActivityType.SESSION_STARTED,
            session_id,
            details={"session_name": session_name}
        )
        self.log_activity(activity)

    def log_session_closed(self, session_id: str):
        """记录Session关闭"""
        activity = Activity(
            ActivityType.SESSION_CLOSED,
            session_id
        )
        self.log_activity(activity)

    def log_config_changed(self, session_id: str, changes: Dict):
        """记录配置更改"""
        activity = Activity(
            ActivityType.CONFIG_CHANGED,
            session_id,
            details=changes
        )
        self.log_activity(activity)

    def log_error(self, session_id: str, error_id: str, context: str):
        """记录错误"""
        activity = Activity(
            ActivityType.ERROR_OCCURRED,
            session_id,
            details={"error_id": error_id, "context": context}
        )
        self.log_activity(activity)

    def log_export_requested(self, session_id: str, export_type: str):
        """记录数据导出请求"""
        activity = Activity(
            ActivityType.EXPORT_REQUESTED,
            session_id,
            details={"export_type": export_type}
        )
        self.log_activity(activity)

    # ==================== 查询 ====================

    def get_session_activities(self, session_id: str) -> List[Dict]:
        """获取Session的所有活动"""
        if session_id not in self.activities:
            return []
        return [a.to_dict() for a in self.activities[session_id]]

    def get_room_activities(self, session_id: str, room_id: str) -> List[Dict]:
        """获取Room的所有活动"""
        if session_id not in self.activities:
            return []
        return [
            a.to_dict()
            for a in self.activities[session_id]
            if a.room_id == room_id
        ]

    def get_activities_by_type(self, session_id: str, activity_type: ActivityType) -> List[Dict]:
        """按类型查询活动"""
        if session_id not in self.activities:
            return []
        return [
            a.to_dict()
            for a in self.activities[session_id]
            if a.activity_type == activity_type.value
        ]

    def get_recent_activities(self, session_id: str, limit: int = 50) -> List[Dict]:
        """获取最近的活动"""
        if session_id not in self.activities:
            return []
        
        activities = self.activities[session_id]
        return [a.to_dict() for a in activities[-limit:]]

    # ==================== 持久化 ====================

    def _save_activity_to_file(self, session_id: str, activity: Activity):
        """将Activity追加保存到文件"""
        log_file = os.path.join(self.log_dir, f"{session_id}_activity.jsonl")
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(activity.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"⚠️ Failed to save activity: {e}")

    def _load_activities_from_disk(self):
        """从磁盘加载所有Activity"""
        for filename in os.listdir(self.log_dir):
            if filename.endswith("_activity.jsonl"):
                session_id = filename.replace("_activity.jsonl", "")
                log_file = os.path.join(self.log_dir, filename)
                
                try:
                    activities = []
                    with open(log_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            data = json.loads(line)
                            activity = Activity.__new__(Activity)
                            activity.__dict__.update(data)
                            activities.append(activity)
                    
                    if activities:
                        self.activities[session_id] = activities
                except Exception as e:
                    print(f"⚠️ Failed to load activities: {e}")

    def get_activity_stats(self, session_id: str) -> Dict:
        """获取Activity统计"""
        if session_id not in self.activities:
            return {}
        
        activities = self.activities[session_id]
        type_count = {}
        
        for activity in activities:
            activity_type = activity.activity_type
            type_count[activity_type] = type_count.get(activity_type, 0) + 1
        
        return {
            "session_id": session_id,
            "total_activities": len(activities),
            "by_type": type_count,
            "first_activity": activities[0].timestamp if activities else None,
            "last_activity": activities[-1].timestamp if activities else None
        }


# 全局实例
activity_logger = ActivityLogger()
