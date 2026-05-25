import json
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional

PARTICIPANT_INDEX_FILE = "config/participant_index.json"


class SessionConfig:
    """
    Configuration for a specific experimental Session.
    """
    def __init__(self, session_id: str, name: str, group_size: int = 2, bot_enabled: bool = True):
        self.session_id = session_id
        self.name = name
        self.group_size = group_size
        self.bot_enabled = bot_enabled
        self.bots = []
        self.history_limit = 10000
        self.created_at = datetime.now()
        self.participant_names = []
        self.spy_mode_enabled = False
        self.session_mode = 1
        self.group_timeout = 30
        # Qualtrics integration (optional)
        self.qualtrics_handoff_enabled = False
        self.qualtrics_store_chat = False
        self.qualtrics_field_transcript = "chat_transcript"
        self.qualtrics_field_status = "chat_status"
        # Conversation control
        self.ai_starts_conversation = False
        self.turn_mode = "none"  # none | round_robin | timed
        self.turn_duration_seconds = 60
        # Matching
        self.assignment_mode = "fifo"  # fifo | stratified

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "name": self.name,
            "group_size": self.group_size,
            "bot_enabled": self.bot_enabled,
            "bots": self.bots,
            "history_limit": self.history_limit,
            "created_at": self.created_at.isoformat(),
            "participant_names": self.participant_names,
            "spy_mode_enabled": self.spy_mode_enabled,
            "session_mode": self.session_mode,
            "group_timeout": self.group_timeout,
            "qualtrics_handoff_enabled": self.qualtrics_handoff_enabled,
            "qualtrics_store_chat": self.qualtrics_store_chat,
            "qualtrics_field_transcript": self.qualtrics_field_transcript,
            "qualtrics_field_status": self.qualtrics_field_status,
            "ai_starts_conversation": self.ai_starts_conversation,
            "turn_mode": self.turn_mode,
            "turn_duration_seconds": self.turn_duration_seconds,
            "assignment_mode": self.assignment_mode,
        }

    @classmethod
    def from_dict(cls, data: Dict):
        obj = cls(
            session_id=data.get("session_id", f"SES-{uuid.uuid4().hex[:5].upper()}"),
            name=data.get("name", "Unnamed Session"),
            group_size=data.get("group_size", 2),
            bot_enabled=data.get("bot_enabled", True),
        )
        obj.bots = data.get("bots", [])
        obj.history_limit = data.get("history_limit", 10000)
        obj.participant_names = data.get("participant_names", [])
        obj.spy_mode_enabled = data.get("spy_mode_enabled", False)
        obj.session_mode = data.get("session_mode", 1)
        obj.group_timeout = data.get("group_timeout", 30)
        obj.qualtrics_handoff_enabled = data.get("qualtrics_handoff_enabled", False)
        obj.qualtrics_store_chat = data.get("qualtrics_store_chat", False)
        obj.qualtrics_field_transcript = data.get("qualtrics_field_transcript", "chat_transcript")
        obj.qualtrics_field_status = data.get("qualtrics_field_status", "chat_status")
        obj.ai_starts_conversation = data.get("ai_starts_conversation", False)
        obj.turn_mode = data.get("turn_mode", "none")
        obj.turn_duration_seconds = data.get("turn_duration_seconds", 60)
        obj.assignment_mode = data.get("assignment_mode", "fifo")
        if "created_at" in data:
            try:
                obj.created_at = datetime.fromisoformat(data["created_at"])
            except ValueError:
                pass
        return obj


class MatchManager:
    def __init__(self):
        self.sessions: Dict[str, SessionConfig] = {}
        self.active_rooms: Dict[str, Dict[str, Dict]] = {}
        self.queues: Dict[str, List[str]] = {}
        self.stratified_queues: Dict[str, Dict[str, List[str]]] = {}
        self.user_locations: Dict[str, Dict[str, str]] = {}
        self.participant_groups: Dict[str, Dict[str, str]] = {}
        self.load_all_sessions()
        self.load_participant_index()

    def load_participant_index(self):
        os.makedirs("config", exist_ok=True)
        if os.path.exists(PARTICIPANT_INDEX_FILE):
            try:
                with open(PARTICIPANT_INDEX_FILE, "r", encoding="utf-8") as f:
                    self.participant_groups = json.load(f)
            except Exception as e:
                print(f"⚠️ Failed to load participant index: {e}")
                self.participant_groups = {}

    def save_participant_index(self):
        os.makedirs("config", exist_ok=True)
        try:
            with open(PARTICIPANT_INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump(self.participant_groups, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ Failed to save participant index: {e}")

    def record_participant_group(self, session_id: str, uid: str, group_id: str):
        if session_id not in self.participant_groups:
            self.participant_groups[session_id] = {}
        self.participant_groups[session_id][uid] = group_id
        self.save_participant_index()

    def get_participant_group_id(self, session_id: str, uid: str) -> Optional[str]:
        if uid in self.user_locations and self.user_locations[uid].get("session_id") == session_id:
            return self.user_locations[uid].get("group_id")
        return self.participant_groups.get(session_id, {}).get(uid)

    def load_all_sessions(self):
        os.makedirs("config", exist_ok=True)
        config_file = "config/sessions.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for sid, sdata in data.items():
                        self.sessions[sid] = SessionConfig.from_dict(sdata)
                        self.active_rooms[sid] = {}
                        self.queues[sid] = []
                        self.stratified_queues[sid] = {}
                print(f"✅ Loaded {len(self.sessions)} experimental sessions from config.")
            except Exception as e:
                print(f"⚠️ Failed to load sessions config: {e}")

    def save_all_sessions(self):
        os.makedirs("config", exist_ok=True)
        config_file = "config/sessions.json"
        try:
            data = {sid: config.to_dict() for sid, config in self.sessions.items()}
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("💾 Session configurations saved to disk.")
        except Exception as e:
            print(f"❌ Failed to save sessions: {e}")

    def create_session(
        self,
        name: str,
        group_size: int,
        bot_enabled: bool,
        bots: List,
        group_timeout: int = 30,
        participant_names: List = None,
        spy_mode_enabled: bool = False,
        session_mode: int = 1,
        qualtrics_handoff_enabled: bool = False,
        qualtrics_store_chat: bool = False,
        qualtrics_field_transcript: str = "chat_transcript",
        qualtrics_field_status: str = "chat_status",
        ai_starts_conversation: bool = False,
        turn_mode: str = "none",
        turn_duration_seconds: int = 60,
        assignment_mode: str = "fifo",
    ) -> str:
        session_id = f"SES-{uuid.uuid4().hex[:5].upper()}"
        config = SessionConfig(session_id, name, group_size, bot_enabled)
        config.bots = bots
        config.group_timeout = group_timeout
        config.participant_names = participant_names or []
        config.spy_mode_enabled = spy_mode_enabled
        config.session_mode = session_mode
        config.qualtrics_handoff_enabled = qualtrics_handoff_enabled
        config.qualtrics_store_chat = qualtrics_store_chat
        config.qualtrics_field_transcript = qualtrics_field_transcript
        config.qualtrics_field_status = qualtrics_field_status
        config.ai_starts_conversation = ai_starts_conversation
        config.turn_mode = turn_mode if turn_mode in ("none", "round_robin", "timed") else "none"
        config.turn_duration_seconds = max(10, turn_duration_seconds)
        config.assignment_mode = assignment_mode if assignment_mode in ("fifo", "stratified") else "fifo"

        self.sessions[session_id] = config
        self.active_rooms[session_id] = {}
        self.queues[session_id] = []
        self.stratified_queues[session_id] = {}
        self.save_all_sessions()
        print(f"🎯 New Session Created: {session_id} ({name})")
        return session_id

    def get_session(self, session_id: str) -> Optional[SessionConfig]:
        return self.sessions.get(session_id)

    def get_all_sessions_summary(self) -> List[Dict]:
        summary = []
        for sid, config in self.sessions.items():
            active_groups = list(self.active_rooms.get(sid, {}).keys())
            summary.append({
                "id": sid,
                "name": config.name,
                "groups": active_groups,
                "group_size": config.group_size,
                "bot_enabled": config.bot_enabled,
                "assignment_mode": config.assignment_mode,
            })
        return summary

    def _normalize_condition(self, condition: Optional[str]) -> str:
        c = (condition or "").strip()
        return c if c else "_default"

    def add_to_queue(self, session_id: str, uid: str, condition: Optional[str] = None) -> Optional[str]:
        if session_id not in self.sessions:
            print(f"⚠️ Warning: Attempted to queue for invalid session {session_id}")
            return None

        if uid in self.user_locations:
            return self.user_locations[uid].get("group_id")

        session_config = self.sessions[session_id]

        if session_config.assignment_mode == "stratified":
            return self._add_to_stratified_queue(session_id, uid, condition, session_config)
        return self._add_to_fifo_queue(session_id, uid, session_config)

    def _add_to_fifo_queue(self, session_id: str, uid: str, session_config: SessionConfig) -> Optional[str]:
        queue = self.queues[session_id]
        if uid not in queue:
            queue.append(uid)
            print(f"⏳ {uid} joined FIFO queue for [{session_id}]. (size: {len(queue)})")

        if len(queue) >= session_config.group_size:
            matched_members = queue[: session_config.group_size]
            self.queues[session_id] = queue[session_config.group_size :]
            group_id = f"GRP-{uuid.uuid4().hex[:4].upper()}"
            self.create_group(session_id, group_id, matched_members)
            return group_id
        return None

    def _add_to_stratified_queue(
        self, session_id: str, uid: str, condition: Optional[str], session_config: SessionConfig
    ) -> Optional[str]:
        cond = self._normalize_condition(condition)
        if session_id not in self.stratified_queues:
            self.stratified_queues[session_id] = {}
        buckets = self.stratified_queues[session_id]
        if cond not in buckets:
            buckets[cond] = []
        queue = buckets[cond]
        if uid not in queue:
            queue.append(uid)
            print(f"⏳ {uid} joined stratified queue [{session_id}] condition={cond} (size: {len(queue)})")

        if len(queue) >= session_config.group_size:
            matched_members = queue[: session_config.group_size]
            buckets[cond] = queue[session_config.group_size :]
            group_id = f"GRP-{uuid.uuid4().hex[:4].upper()}"
            self.create_group(session_id, group_id, matched_members, condition=cond)
            return group_id
        return None

    def remove_from_queue(self, session_id: str, uid: str, condition: Optional[str] = None):
        if session_id in self.queues and uid in self.queues[session_id]:
            self.queues[session_id].remove(uid)
        if session_id in self.stratified_queues:
            cond = self._normalize_condition(condition)
            q = self.stratified_queues[session_id].get(cond, [])
            if uid in q:
                q.remove(uid)

    def create_group(
        self, session_id: str, group_id: str, members: List[str] = None, condition: Optional[str] = None
    ):
        if session_id not in self.active_rooms:
            self.active_rooms[session_id] = {}

        if group_id not in self.active_rooms[session_id]:
            now = datetime.now()
            self.active_rooms[session_id][group_id] = {
                "members": members if members else [],
                "created_at": now,
                "last_activity": now,
                "condition": self._normalize_condition(condition) if condition else None,
                "opening_sent": False,
                "turn_initialized": False,
            }
            if members:
                for muid in members:
                    self.user_locations[muid] = {"session_id": session_id, "group_id": group_id}
                    self.record_participant_group(session_id, muid, group_id)
            print(f"🏠 Group {group_id} under {session_id} (Members: {members}, condition: {condition})")
        return group_id

    def get_group_info(self, session_id: str, group_id: str) -> Optional[Dict]:
        if session_id in self.active_rooms and group_id in self.active_rooms[session_id]:
            return self.active_rooms[session_id][group_id]
        return None

    def end_group(self, session_id: str, group_id: str):
        if session_id in self.active_rooms and group_id in self.active_rooms[session_id]:
            group_info = self.active_rooms[session_id][group_id]
            for muid in group_info.get("members", []):
                if muid in self.user_locations:
                    del self.user_locations[muid]
            del self.active_rooms[session_id][group_id]
            print(f"🔚 Group {group_id} in Session {session_id} closed.")


match_manager = MatchManager()
