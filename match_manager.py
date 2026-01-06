import json
from datetime import datetime
from typing import Dict, List, Optional
import os


class AdminConfig:
    """Admin configuration - with file persistence"""

    def __init__(self):
        self.group_size = 2
        self.duration = 10  # in minutes
        self.bot_enabled = True
        self.bot_delay = 2
        self.bot_name = "Bot"
        self.bot_prompt = ""
        self.match_timeout = 180  # in seconds

        # Load config from file on startup
        self.load_from_file()

    def load_from_file(self):
        """Load configuration from file"""
        config_file = "config/admin_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.group_size = data.get('group_size', 2)
                    self.duration = data.get('duration', 10)
                    self.bot_enabled = data.get('bot_enabled', True)
                    self.bot_delay = data.get('bot_delay', 2)
                    self.bot_name = data.get('bot_name', 'Bot')
                    self.bot_prompt = data.get('bot_prompt', '')
                    self.match_timeout = data.get('match_timeout', 180)
                    print(f"✅ Admin config loaded from {config_file}")
                    print(f"   ⚙️  Group size: {self.group_size}")
                    print(f"   🤖 Bot enabled: {self.bot_enabled}")
                    print(f"   🎤 Bot name: {self.bot_name}")
            except Exception as e:
                print(f"⚠️ Failed to load config from file: {e}")
                print(f"   Using default values")
        else:
            print(f"⚠️ Config file not found: {config_file}")
            print(f"   Using default values. File will be created on first save.")

    def save_to_file(self):
        """Save configuration to file"""
        os.makedirs("config", exist_ok=True)
        config_file = "config/admin_config.json"
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
                print(f"💾 Admin config saved to {config_file}")
        except Exception as e:
            print(f"❌ Failed to save config: {e}")

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "group_size": self.group_size,
            "duration": self.duration,
            "bot_enabled": self.bot_enabled,
            "bot_delay": self.bot_delay,
            "bot_name": self.bot_name,
            "bot_prompt": self.bot_prompt,
            "match_timeout": self.match_timeout
        }

    def set_group_size(self, size: int):
        """Set group size and save"""
        self.group_size = size
        self.save_to_file()
        print(f"✅ Group size set to {size}")

    def set_duration(self, minutes: int):
        """Set chat duration and save"""
        self.duration = minutes
        self.save_to_file()
        print(f"✅ Chat duration set to {minutes} minutes")

    def set_bot_name(self, name: str):
        """Set bot name and save"""
        if name and len(name) <= 50:
            self.bot_name = name
            self.save_to_file()
            print(f"✅ Bot name set to '{name}'")

    def set_bot_prompt(self, prompt: str):
        """Set bot prompt and save"""
        self.bot_prompt = prompt
        self.save_to_file()
        print(f"✅ Bot prompt updated")

    def set_bot_enabled(self, enabled: bool):
        """Set bot enabled status and save"""
        self.bot_enabled = enabled
        self.save_to_file()
        status = "enabled" if enabled else "disabled"
        print(f"✅ Bot {status}")


class MatchManager:
    """Manages participant matching and room creation"""

    def __init__(self, group_size: int = 2):
        self.group_size = group_size
        self.queues: Dict[str, List[str]] = {}  # condition -> [uid, uid, ...]
        self.active_rooms: Dict[str, Dict] = {}  # room_id -> room_data
        self.user_to_room: Dict[str, str] = {}  # uid -> room_id
        self.user_to_queue: Dict[str, str] = {}  # uid -> condition
        self.total_sessions = 0
        self.admin_config: Optional[AdminConfig] = None  # Will be set externally

    def set_admin_config(self, admin_config: AdminConfig):
        """Set admin configuration reference"""
        self.admin_config = admin_config
        self.group_size = admin_config.group_size
        print(f"✅ MatchManager linked with AdminConfig (group_size: {self.group_size})")

    def join_queue(self, uid: str, condition: str = "default") -> Optional[str]:
        """
        Join queue and try to match

        Parameters:
        - uid: User ID
        - condition: Matching condition (default: "default")

        Return: partner_id if matched, None if still waiting
        """
        if condition not in self.queues:
            self.queues[condition] = []

        # Don't add if already in queue
        if uid in self.user_to_queue:
            print(f"⚠️ {uid} is already in queue")
            return None

        queue = self.queues[condition]
        queue.append(uid)
        self.user_to_queue[uid] = condition

        queue_size = len(queue)
        required_size = self.group_size

        print(f"⏳ {uid} joined queue '{condition}' "
              f"(Queue: {queue_size}/{required_size}, Users: {', '.join(queue)})")

        # Try to match
        if queue_size >= required_size:
            return self.match_group(condition)

        return None

    def match_group(self, condition: str) -> Optional[str]:
        """
        Match a group of participants

        Parameters:
        - condition: Matching condition

        Return: partner_id (for group_size=2)
        """
        queue = self.queues.get(condition, [])
        queue_size = len(queue)
        required_size = self.group_size

        if queue_size < required_size:
            print(f"⚠️ Not enough users in queue '{condition}' ({queue_size}/{required_size})")
            return None

        # Take first N users from queue
        group = queue[:required_size]
        queue[:required_size] = []  # Remove from queue

        # Create room
        room_id = self.create_room(group)

        # Remove from queue tracking
        for uid in group:
            if uid in self.user_to_queue:
                del self.user_to_queue[uid]

        # Return partner info (for group_size=2: [user1, user2])
        partner_id = group[1] if len(group) > 1 else None

        print(f"✅ Match successful: Room {room_id} created with users: {', '.join(group)}")
        print(f"   📊 Remaining in queue '{condition}': {len(queue)} users")

        return partner_id

    def create_room(self, room_id, members=None):
    # If no members are provided, initialize as an empty list
     if members is None:
        members = []
    
    # Now we can safely copy the list
        self.active_rooms[room_id] = {
        "members": members.copy() if isinstance(members, list) else [members],
        "ws_connections": [],
        "created_at": datetime.now(),
        "bot_enabled": getattr(self.admin_config, 'bot_enabled', False)
        }
        return room_id
    def leave_queue(self, uid: str, condition: str = "default"):
        """
        Leave queue

        Parameters:
        - uid: User ID
        - condition: Matching condition
        """
        if condition in self.queues and uid in self.queues[condition]:
            self.queues[condition].remove(uid)
            print(f"🚪 {uid} left queue '{condition}'")

        if uid in self.user_to_queue:
            del self.user_to_queue[uid]

    def end_room(self, room_id: str):
        """
        End a room session

        Parameters:
        - room_id: Room ID to end
        """
        if room_id in self.active_rooms:
            room_info = self.active_rooms[room_id]
            members = room_info.get("members", [])

            for uid in members:
                if uid in self.user_to_room:
                    del self.user_to_room[uid]

            del self.active_rooms[room_id]
            print(f"🔚 Room {room_id} ended (Users: {', '.join(members)})")

    def get_queue_status(self, condition: str = "default") -> Dict:
        """Get queue status"""
        queue = self.queues.get(condition, [])
        return {
            "condition": condition,
            "queue_length": len(queue),
            "required_size": self.group_size,
            "queued_users": queue.copy(),
            "status": "ready" if len(queue) >= self.group_size else "waiting"
        }

    def get_active_rooms_count(self) -> int:
        """Get number of active rooms"""
        return len(self.active_rooms)

    def get_room_info(self, room_id: str) -> Optional[Dict]:
        """Get room information"""
        if room_id in self.active_rooms:
            room_data = self.active_rooms[room_id]
            created_at = room_data.get("created_at")

            # Format created_at timestamp
            if isinstance(created_at, datetime):
                created_at_str = created_at.isoformat()
            else:
                created_at_str = str(created_at)

            return {
                "room_id": room_id,
                "members": room_data.get("members", []).copy(),
                "created_at": created_at_str,
                "connection_count": len(room_data.get("ws_connections", [])),
                "bot_enabled": room_data.get("bot_enabled", False),
                "age_seconds": (datetime.now() - created_at).total_seconds() if isinstance(created_at, datetime) else 0
            }
        return None

    def get_all_rooms_info(self) -> Dict[str, Dict]:
        """Get information for all active rooms"""
        return {room_id: self.get_room_info(room_id) for room_id in self.active_rooms}

    def cleanup_inactive_users(self, timeout_seconds: int = 300):
        """Clean up users who have been in queue for too long"""
        current_time = datetime.now()
        cleaned_count = 0

        for condition, queue in self.queues.items():
            # In a real implementation, you'd track join times for each user
            # For now, we'll just clean up old rooms
            pass

        print(f"🧹 Cleanup completed ({cleaned_count} users removed)")


# ============= Global instances =============

admin_config = AdminConfig()
match_manager = MatchManager(admin_config.group_size)
match_manager.set_admin_config(admin_config)  # Important: link admin config

# ============= Initialization Logging =============

if __name__ == "__main__":
    print("✅ match_manager.py module loaded successfully")
    print(f"📊 Admin config:")
    print(f"   ⚙️  Group size: {admin_config.group_size}")
    print(f"   ⏱️  Duration: {admin_config.duration} minutes")
    print(f"   🤖 Bot enabled: {admin_config.bot_enabled}")
    print(f"   🎤 Bot name: {admin_config.bot_name}")
    print(f"   ⏳ Bot delay: {admin_config.bot_delay}s")
    print(f"   ⏰ Match timeout: {admin_config.match_timeout}s")
    print(f"\n📈 Match Manager:")
    print(f"   🎯 Group size: {match_manager.group_size}")
    print(f"   🔗 Admin config linked: {match_manager.admin_config is not None}")