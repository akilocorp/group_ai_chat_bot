import json
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional

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

        self.load_from_file()

    def load_from_file(self):
        os.makedirs("config", exist_ok=True)
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
                    print(f"✅ Admin config loaded.")
            except Exception as e:
                print(f"⚠️ Failed to load config: {e}")

    def save_to_file(self):
        os.makedirs("config", exist_ok=True)
        config_file = "config/admin_config.json"
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
                print(f"💾 Admin config saved.")
        except Exception as e:
            print(f"❌ Failed to save config: {e}")

    def to_dict(self) -> Dict:
        return {
            "group_size": self.group_size,
            "duration": self.duration,
            "bot_enabled": self.bot_enabled,
            "bot_delay": self.bot_delay,
            "bot_name": self.bot_name,
            "bot_prompt": self.bot_prompt,
            "match_timeout": self.match_timeout
        }



class MatchManager:
    """Manages participant matching, room creation, and lobby tracking"""

    def __init__(self, group_size: int = 2):
        self.group_size = group_size
        self.queues: Dict[str, List[str]] = {}  # condition -> [uid, uid, ...]
        self.active_rooms: Dict[str, Dict] = {} # room_id -> room_data
        self.user_to_room: Dict[str, str] = {}  # uid -> room_id
        self.user_to_queue: Dict[str, str] = {} # uid -> condition
        self.admin_config: Optional[AdminConfig] = None

    def set_admin_config(self, admin_config: AdminConfig):
        self.admin_config = admin_config
        self.group_size = admin_config.group_size

    # ============ AUTOMATED MATCHING (wait.html) ============

    def add_to_queue(self, uid: str, condition: str = "default") -> Optional[List[str]]:
        """Adds user to queue and returns a list of users if a match is formed."""
        if uid in self.user_to_room:
            return None # Already in a room
            
        if condition not in self.queues:
            self.queues[condition] = []

        if uid not in self.queues[condition]:
            self.queues[condition].append(uid)
            self.user_to_queue[uid] = condition
            print(f"⏳ {uid} added to queue [{condition}]")

        # Check if we hit the group size requirement
        if len(self.queues[condition]) >= self.group_size:
            matched_group = self.queues[condition][:self.group_size]
            self.queues[condition] = self.queues[condition][self.group_size:]
            
            # Cleanup queue tracking
            for user in matched_group:
                if user in self.user_to_queue:
                    del self.user_to_queue[user]
                    
            return matched_group
        
        return None

    def remove_from_queue(self, uid: str, condition: str = "default"):
        if condition in self.queues and uid in self.queues[condition]:
            self.queues[condition].remove(uid)
        if uid in self.user_to_queue:
            del self.user_to_queue[uid]
        print(f"🚪 {uid} left queue [{condition}]")

    # ============ ROOM MANAGEMENT (Lobby + Matched) ============

    def create_room(self, room_id: str, members: List[str] = None):
        """Initializes a room in memory for WebSockets."""
        if room_id not in self.active_rooms:
            self.active_rooms[room_id] = {
                "members": members if members else [],
                "ws_connections": [],
                "created_at": datetime.now(),
                "bot_enabled": getattr(self.admin_config, 'bot_enabled', False)
            }
            # Update user tracking
            if members:
                for uid in members:
                    self.user_to_room[uid] = room_id
            
            print(f"🏠 Room Created: {room_id} (Members: {members})")
        return room_id

    def end_room(self, room_id: str):
        if room_id in self.active_rooms:
            room_info = self.active_rooms[room_id]
            for uid in room_info.get("members", []):
                if uid in self.user_to_room:
                    del self.user_to_room[uid]
            del self.active_rooms[room_id]
            print(f"🔚 Room {room_id} closed.")

    def get_room_info(self, room_id: str) -> Optional[Dict]:
        if room_id in self.active_rooms:
            data = self.active_rooms[room_id]
            return {
                "room_id": room_id,
                "user_count": len(data["members"]),
                "connection_count": len(data["ws_connections"]),
                "age_seconds": (datetime.now() - data["created_at"]).total_seconds()
            }
        return None

# ============= Global instances =============
admin_config = AdminConfig()
match_manager = MatchManager(admin_config.group_size)
match_manager.set_admin_config(admin_config)

# Verify group size on startup
print(f"DEBUG: MatchManager initialized with group_size: {match_manager.group_size}")