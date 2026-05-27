import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import os
from collections import defaultdict


class ConversationContext:
    """Manages conversation context for a single room, optimized for multi-bot sensing"""

    # Limit context size to avoid excessive memory usage
    MAX_MESSAGES_PER_ROOM = 50000  # Room message store (context budget is char-limited separately)
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
        """Add message to history and update user profiling if sender is human"""
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        message = {
            "sender": sender,
            "text": text,
            "timestamp": timestamp,
            "turn": len(self.messages) + 1
        }

        # Handle sliding window logic
        if len(self.messages) >= self.MAX_MESSAGES_PER_ROOM:
            self.messages.pop(0)
            # Re-index turns
            for i, msg in enumerate(self.messages, 1):
                msg["turn"] = i
            message["turn"] = len(self.messages) + 1

        self.messages.append(message)
        self.last_activity = datetime.now()

        # UPDATED: More robust bot-detection to keep user profiles clean
        # We ignore senders that are known bots or contain "Bot"/"Assistant"
        is_bot = any(marker in sender.lower() for marker in ["bot", "assistant", "system"])
        
        if not is_bot:
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

            # Extract and limit keywords
            keywords = self._extract_keywords(text)
            profile["keywords"].extend(keywords)
            if len(profile["keywords"]) > self.MAX_KEYWORDS_PER_USER:
                profile["keywords"] = profile["keywords"][-self.MAX_KEYWORDS_PER_USER:]

        # Log entry
        log_text = text[:50] + "..." if len(text) > 50 else text
        print(f"💬 [{self.room_id}] {sender}: {log_text}")

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from message (simple version)"""
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
        keywords = [w for w in words if len(w) > 2 and w not in stopwords]
        return list(set(keywords))

    def get_context_summary(
        self,
        num_messages: int = None,
        max_chars: int = 100_000,
    ) -> str:
        """
        Build prompt context from recent messages, capped by character budget (admin setting).
        """
        if not self.messages:
            return f"## Conversation Context (Room: {self.room_id})\nNo messages yet."

        max_chars = max(10_000, min(10_000_000, int(max_chars)))
        header = f"""## Conversation Context (Room: {self.room_id})
**Participants**: {', '.join(self.user_profiles.keys()) if self.user_profiles else 'System Only'}
**Total Turns**: {len(self.messages)}
**Last Activity**: {self.last_activity.strftime('%Y-%m-%d %H:%M:%S')}

### Recent messages (up to {max_chars:,} characters):
"""
        recent = []
        used = len(header)
        for msg in reversed(self.messages):
            line = f"\n[{msg['turn']}] **{msg['sender']}**: {msg['text']}"
            if used + len(line) > max_chars:
                break
            recent.insert(0, msg)
            used += len(line)

        if num_messages is not None and num_messages > 0:
            recent = recent[-int(num_messages) :]

        context = header.replace(
            f"up to {max_chars:,} characters",
            f"{len(recent)} messages, ~{used:,} characters",
        )
        for msg in recent:
            context += f"\n[{msg['turn']}] **{msg['sender']}**: {msg['text']}"

        if self.user_profiles:
            context += "\n\n### Human User Insights:"
            for user, profile in self.user_profiles.items():
                recent_keywords = list(set(profile['keywords'][-5:])) if profile['keywords'] else []
                keywords_str = ', '.join(recent_keywords) if recent_keywords else "None"
                context += f"\n- **{user}**: {profile['message_count']} msgs. Interests: {keywords_str}"

        return context

    def _get_duration(self) -> str:
        """Calculate conversation duration"""
        if not self.messages:
            return "Not started"
        first_time = datetime.fromisoformat(self.messages[0]['timestamp'])
        last_time = datetime.fromisoformat(self.messages[-1]['timestamp'])
        duration = last_time - first_time
        
        if duration.days > 0:
            return f"{duration.days}d {duration.seconds // 3600}h"
        elif duration.seconds >= 3600:
            return f"{duration.seconds // 3600}h {(duration.seconds % 3600) // 60}m"
        else:
            return f"{duration.seconds // 60}m {duration.seconds % 60}s"

    def get_user_info(self, user: str) -> Dict:
        return self.user_profiles.get(user, {})

    def to_dict(self) -> Dict:
        return {
            "room_id": self.room_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "messages": self.messages[-100:],  # Save last 100 for persistence
            "user_profiles": self.user_profiles,
            "total_turns": len(self.messages),
            "summary": self.get_statistics()
        }

    def save_to_file(self, filepath: str):
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            print(f"💾 Conversation saved: {filepath}")
        except Exception as e:
            print(f"❌ Save failed: {e}")

    def get_statistics(self) -> Dict:
        total_chars = sum(len(msg['text']) for msg in self.messages) if self.messages else 0
        avg_len = total_chars / len(self.messages) if self.messages else 0
        return {
            "room_id": self.room_id,
            "total_messages": len(self.messages),
            "total_participants": len(self.user_profiles),
            "avg_length": round(avg_len, 1),
            "duration": self._get_duration(),
            "last_activity": self.last_activity.isoformat()
        }

    def get_size_info(self) -> Dict:
        """Old helper kept for compatibility"""
        message_memory = sum(len(str(msg)) for msg in self.messages)
        user_memory = sum(len(str(p)) for p in self.user_profiles.values())
        return {
            "room_id": self.room_id,
            "message_count": len(self.messages),
            "estimated_kb": (message_memory + user_memory) / 1024,
            "max_allowed": self.MAX_MESSAGES_PER_ROOM,
            "remaining": self.MAX_MESSAGES_PER_ROOM - len(self.messages)
        }

    def clear_old_messages(self, keep_last: int = 100):
        """Old helper kept for compatibility"""
        if len(self.messages) > keep_last:
            removed = len(self.messages) - keep_last
            self.messages = self.messages[-keep_last:]
            return removed
        return 0


def resolve_context_max_chars(bot_cfg: dict = None) -> int:
    """Character budget for bot context (admin: context_max_chars, legacy: context_messages × 80)."""
    if not bot_cfg:
        return 100_000
    if bot_cfg.get("context_max_chars") is not None:
        return max(10_000, min(10_000_000, int(bot_cfg["context_max_chars"])))
    legacy_msgs = int(bot_cfg.get("context_messages", 20) or 20)
    return max(10_000, min(10_000_000, legacy_msgs * 80))


# ==========================================
# GLOBAL MANAGER FUNCTIONS
# ==========================================

conversation_contexts: Dict[str, ConversationContext] = {}

def get_or_create_context(room_id: str) -> ConversationContext:
    if room_id not in conversation_contexts:
        conversation_contexts[room_id] = ConversationContext(room_id)
    else:
        conversation_contexts[room_id].last_activity = datetime.now()
    return conversation_contexts[room_id]

def get_context(room_id: str) -> Optional[ConversationContext]:
    return conversation_contexts.get(room_id)

def remove_context(room_id: str, save_to_file: bool = True):
    if room_id in conversation_contexts:
        context = conversation_contexts[room_id]
        if save_to_file:
            os.makedirs("conversations", exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            context.save_to_file(f"conversations/{room_id}_{ts}.json")
        del conversation_contexts[room_id]
        print(f"🗑️ Context removed: {room_id}")

def save_all_contexts(directory: str = "conversations"):
    os.makedirs(directory, exist_ok=True)
    for rid, ctx in conversation_contexts.items():
        ctx.save_to_file(os.path.join(directory, f"{rid}.json"))

def cleanup_inactive_contexts(max_inactive_minutes: int = 60):
    now = datetime.now()
    to_remove = [rid for rid, ctx in conversation_contexts.items() 
                 if (now - ctx.last_activity).total_seconds() / 60 > max_inactive_minutes]
    for rid in to_remove:
        remove_context(rid)
    return len(to_remove)

def get_global_statistics() -> Dict:
    total_msgs = sum(len(ctx.messages) for ctx in conversation_contexts.values())
    return {
        "total_rooms": len(conversation_contexts),
        "total_messages": total_msgs,
        "room_ids": list(conversation_contexts.keys())
    }

# ============= Initialization Logging =============

if __name__ == "__main__":
    print("✅ context_manager.py loaded.")
    # Quick Test
    ctx = get_or_create_context("test_room")
    ctx.add_message("User1", "Hello Jarvis, what is the weather?")
    ctx.add_message("Jarvis", "I am an AI, I don't feel weather but it looks sunny!")
    print(ctx.get_context_summary(num_messages=2))