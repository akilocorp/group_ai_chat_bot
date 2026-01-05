import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import os
from collections import defaultdict


class ConversationContext:
    """Manages conversation context for a single room"""

    # Limit context size to avoid excessive memory usage
    MAX_MESSAGES_PER_ROOM = 1000  # Maximum 1000 messages stored per chat room
    MAX_KEYWORDS_PER_USER = 50   # Maximum 50 keywords stored per user

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.messages: List[Dict] = []  # Complete message history
        self.user_profiles: Dict[str, Dict] = {}  # User profiles
        self.topic_history: List[str] = []  # Topic history
        self.created_at = datetime.now()
        self.last_activity = datetime.now()

        print(f"📝 ConversationContext created for room {room_id}")

    def add_message(self, sender: str, text: str, timestamp: str = None):
        """Add message to history"""
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        message = {
            "sender": sender,
            "text": text,
            "timestamp": timestamp,
            "turn": len(self.messages) + 1
        }

        # 检查是否超过最大消息限制
        if len(self.messages) >= self.MAX_MESSAGES_PER_ROOM:
            # 移除最早的消息
            self.messages.pop(0)
            # 需要重新编号所有消息的turn
            for i, msg in enumerate(self.messages, 1):
                msg["turn"] = i
            message["turn"] = len(self.messages) + 1

        self.messages.append(message)
        self.last_activity = datetime.now()

        # Update user profile (only for real users, not bot)
        if sender.lower() != "bot" and not sender.startswith("Bot"):
            if sender not in self.user_profiles:
                self.user_profiles[sender] = {
                    "message_count": 0,
                    "first_message": timestamp,
                    "last_message": timestamp,
                    "keywords": [],
                    "interaction_style": "neutral",
                    "avg_message_length": 0,
                    "total_chars": 0
                }

            profile = self.user_profiles[sender]
            profile["message_count"] += 1
            profile["last_message"] = timestamp
            profile["total_chars"] += len(text)
            profile["avg_message_length"] = profile["total_chars"] / profile["message_count"]

            # Extract keywords (simple implementation)
            keywords = self._extract_keywords(text)

            # 限制关键词数量
            profile["keywords"].extend(keywords)
            if len(profile["keywords"]) > self.MAX_KEYWORDS_PER_USER:
                # 保留最近的关键词
                profile["keywords"] = profile["keywords"][-self.MAX_KEYWORDS_PER_USER:]

        # 限制日志输出长度
        log_text = text[:50] + "..." if len(text) > 50 else text
        print(f"💬 [{self.room_id}] {sender}: {log_text}")

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from message (simple version)"""
        # Filter out common stopwords
        stopwords = {
            'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'is', 'am', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'shall', 'should', 'may', 'might', 'must', 'can', 'could', 'i', 'you',
            'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
            'my', 'your', 'his', 'its', 'our', 'their', 'mine', 'yours', 'hers',
            'ours', 'theirs', 'this', 'that', 'these', 'those', 'here', 'there',
            'what', 'which', 'who', 'whom', 'whose', 'when', 'where', 'why', 'how'
        }

        words = text.lower().split()
        # 只保留长度大于2且不在停用词列表中的词
        keywords = [w for w in words if len(w) > 2 and w not in stopwords]

        # 去重
        return list(set(keywords))

    def get_context_summary(self, num_messages: int = 10) -> str:
        """
        Generate context summary for AI bot usage
        """
        if not self.messages:
            return f"## Conversation Context (Room: {self.room_id})\nNo messages yet."

        recent = self.messages[-num_messages:] if len(self.messages) > 0 else []

        context = f"""
## Conversation Context (Room: {self.room_id})

**Participants**: {', '.join(self.user_profiles.keys()) if self.user_profiles else 'None'}
**Total Turns**: {len(self.messages)}
**Duration**: {self._get_duration()}
**Last Activity**: {self.last_activity.strftime('%Y-%m-%d %H:%M:%S')}

### Recent {min(num_messages, len(recent))} Messages:
"""
        for msg in recent:
            context += f"\n[{msg['turn']}] **{msg['sender']}**: {msg['text']}"

        # Add user information if available
        if self.user_profiles:
            context += "\n\n### User Information:"
            for user, profile in self.user_profiles.items():
                # 获取最近的关键词（最多5个）
                recent_keywords = list(set(profile['keywords'][-5:])) if profile['keywords'] else []
                keywords_str = ', '.join(recent_keywords) if recent_keywords else "None"

                context += (f"\n- **{user}**: {profile['message_count']} messages, "
                            f"Avg length: {profile['avg_message_length']:.1f} chars, "
                            f"Recent keywords: {keywords_str}")

        return context

    def _get_duration(self) -> str:
        """Calculate conversation duration"""
        if not self.messages:
            return "Not started"

        first_time = datetime.fromisoformat(self.messages[0]['timestamp'])
        last_time = datetime.fromisoformat(self.messages[-1]['timestamp'])
        duration = last_time - first_time

        if duration.days > 0:
            return f"{duration.days} days, {duration.seconds // 3600} hours"
        elif duration.seconds >= 3600:
            hours = duration.seconds // 3600
            minutes = (duration.seconds % 3600) // 60
            return f"{hours}h {minutes}m"
        elif duration.seconds >= 60:
            minutes = duration.seconds // 60
            seconds = duration.seconds % 60
            return f"{minutes}m {seconds}s"
        else:
            return f"{duration.seconds}s"

    def get_user_info(self, user: str) -> Dict:
        """Get user information"""
        return self.user_profiles.get(user, {})

    def to_dict(self) -> Dict:
        """Export as dictionary (for saving to database or file)"""
        return {
            "room_id": self.room_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "messages": self.messages[-100:],  # 只保存最近100条消息以减少文件大小
            "user_profiles": self.user_profiles,
            "total_turns": len(self.messages),
            "active_participants": len(self.user_profiles),
            "summary": self.get_statistics()
        }

    def save_to_file(self, filepath: str):
        """Save conversation to JSON file"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            print(f"💾 Conversation saved: {filepath} ({len(self.messages)} messages)")
        except Exception as e:
            print(f"❌ Failed to save conversation: {e}")

    def get_statistics(self) -> Dict:
        """Get conversation statistics"""
        total_chars = sum(len(msg['text']) for msg in self.messages) if self.messages else 0
        avg_msg_length = total_chars / len(self.messages) if self.messages else 0

        return {
            "room_id": self.room_id,
            "total_messages": len(self.messages),
            "total_participants": len(self.user_profiles),
            "total_characters": total_chars,
            "average_message_length": round(avg_msg_length, 1),
            "participant_messages": {
                user: profile["message_count"]
                for user, profile in self.user_profiles.items()
            },
            "duration": self._get_duration(),
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "is_active": (datetime.now() - self.last_activity).seconds < 300  # 5分钟内活跃
        }

    def get_size_info(self) -> Dict:
        """Get information about context size"""
        total_messages = len(self.messages)
        total_users = len(self.user_profiles)

        # 估算内存使用（粗略估计）
        message_memory = sum(len(str(msg)) for msg in self.messages)
        user_memory = sum(len(str(profile)) for profile in self.user_profiles.values())

        return {
            "room_id": self.room_id,
            "message_count": total_messages,
            "user_count": total_users,
            "estimated_memory_kb": (message_memory + user_memory) / 1024,
            "max_messages_allowed": self.MAX_MESSAGES_PER_ROOM,
            "messages_remaining": self.MAX_MESSAGES_PER_ROOM - total_messages
        }

    def clear_old_messages(self, keep_last: int = 100):
        """Clear old messages, keep only recent ones"""
        if len(self.messages) > keep_last:
            removed = len(self.messages) - keep_last
            self.messages = self.messages[-keep_last:]
            print(f"🧹 Cleared {removed} old messages from room {self.room_id}")
            return removed
        return 0


# Global manager: tracks context for all rooms
conversation_contexts: Dict[str, ConversationContext] = {}


def get_or_create_context(room_id: str) -> ConversationContext:
    """Get or create conversation context for a room"""
    if room_id not in conversation_contexts:
        conversation_contexts[room_id] = ConversationContext(room_id)
        print(f"📝 Created new context for room {room_id}")
    else:
        # 更新最后活动时间
        conversation_contexts[room_id].last_activity = datetime.now()

    return conversation_contexts[room_id]


def get_context(room_id: str) -> Optional[ConversationContext]:
    """Get existing context"""
    return conversation_contexts.get(room_id)


def remove_context(room_id: str, save_to_file: bool = True):
    """Remove context (when room ends)"""
    if room_id in conversation_contexts:
        context = conversation_contexts[room_id]

        # 保存到文件
        if save_to_file:
            try:
                os.makedirs("conversations", exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"conversations/{room_id}_{timestamp}.json"
                context.save_to_file(filename)
                print(f"💾 Conversation saved to: {filename}")
            except Exception as e:
                print(f"⚠️ Failed to save conversation: {e}")

        # 清理内存
        del conversation_contexts[room_id]
        print(f"🗑️ Context cleaned up: {room_id} ({len(context.messages)} messages)")


def get_all_contexts() -> Dict[str, ConversationContext]:
    """Get all active conversation contexts"""
    return conversation_contexts.copy()


def save_all_contexts(directory: str = "conversations"):
    """Save all conversation contexts to files"""
    try:
        os.makedirs(directory, exist_ok=True)
        saved_count = 0

        for room_id, context in conversation_contexts.items():
            try:
                filepath = os.path.join(directory, f"{room_id}.json")
                context.save_to_file(filepath)
                saved_count += 1
            except Exception as e:
                print(f"⚠️ Failed to save conversation {room_id}: {e}")

        print(f"💾 All {saved_count}/{len(conversation_contexts)} conversations saved to {directory}/")
    except Exception as e:
        print(f"❌ Failed to save all conversations: {e}")


def cleanup_inactive_contexts(max_inactive_minutes: int = 60):
    """Clean up contexts that have been inactive for too long"""
    current_time = datetime.now()
    removed_count = 0

    rooms_to_remove = []

    for room_id, context in conversation_contexts.items():
        inactive_minutes = (current_time - context.last_activity).total_seconds() / 60

        if inactive_minutes > max_inactive_minutes:
            rooms_to_remove.append(room_id)

    for room_id in rooms_to_remove:
        remove_context(room_id, save_to_file=True)
        removed_count += 1

    if removed_count > 0:
        print(f"🧹 Cleaned up {removed_count} inactive contexts")

    return removed_count


def get_global_statistics() -> Dict:
    """Get statistics for all conversation contexts"""
    total_messages = sum(len(ctx.messages) for ctx in conversation_contexts.values())
    total_users = sum(len(ctx.user_profiles) for ctx in conversation_contexts.values())

    return {
        "total_rooms": len(conversation_contexts),
        "total_messages": total_messages,
        "total_users": total_users,
        "avg_messages_per_room": total_messages / len(conversation_contexts) if conversation_contexts else 0,
        "active_rooms": [room_id for room_id, ctx in conversation_contexts.items()
                         if (datetime.now() - ctx.last_activity).seconds < 300],
        "room_ids": list(conversation_contexts.keys())
    }


def cleanup_inactive_contexts(max_inactive_minutes: int = 60):
    """Clean up contexts that have been inactive for too long"""
    current_time = datetime.now()
    removed_count = 0

    rooms_to_remove = []

    for room_id, context in conversation_contexts.items():
        inactive_minutes = (current_time - context.last_activity).total_seconds() / 60

        if inactive_minutes > max_inactive_minutes:
            rooms_to_remove.append(room_id)

    for room_id in rooms_to_remove:
        remove_context(room_id, save_to_file=True)
        removed_count += 1

    if removed_count > 0:
        print(f"🧹 Cleaned up {removed_count} inactive contexts")

    return removed_count


# ============= Initialization Logging =============

if __name__ == "__main__":
    print("✅ context_manager.py module loaded successfully")
    print(f"📊 Configuration:")
    print(f"   Max messages per room: {ConversationContext.MAX_MESSAGES_PER_ROOM}")
    print(f"   Max keywords per user: {ConversationContext.MAX_KEYWORDS_PER_USER}")

    # Test context creation
    print("\n🧪 Testing context creation...")

    ctx1 = get_or_create_context("room_1")
    ctx1.add_message("alice", "Hi, how are you?")
    ctx1.add_message("bob", "I'm doing great, thanks!")
    ctx1.add_message("alice", "That's wonderful! What have you been up to lately?")

    print(f"\n📊 Context summary:\n{ctx1.get_context_summary()}")
    print(f"\n📈 Statistics: {ctx1.get_statistics()}")
    print(f"\n📏 Size info: {ctx1.get_size_info()}")

    # Test global statistics
    print(f"\n🌍 Global stats: {get_global_statistics()}")

    # Test cleanup function
    print(f"\n🧹 Test cleanup function...")
    cleaned = cleanup_inactive_contexts(max_inactive_minutes=0.1)  # 清理超过6秒不活跃的
    print(f"Cleaned {cleaned} inactive contexts")