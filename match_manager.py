import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from study_conditions import assign_group_disclosure

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
        # Survey open for N days; each group chat lasts M minutes (from group formation)
        self.survey_open_days = 7
        self.group_chat_duration_minutes = 5
        # Qualtrics integration (optional)
        self.qualtrics_handoff_enabled = True
        self.qualtrics_store_chat = True
        self.qualtrics_field_transcript = "transcript"
        self.qualtrics_field_status = "chat_status"  # legacy; unused by Qualtrics snippet
        # Conversation control
        self.ai_starts_conversation = False
        self.turn_mode = "none"  # none | round_robin | timed
        self.turn_duration_seconds = 60
        # Matching
        self.assignment_mode = "fifo"  # fifo | stratified
        # Qualtrics embed `condition` param: disclosure labels + stratified queues
        self.condition_enabled = True
        # Optional: other personas mimic one teammate's length/tone
        self.style_mimic_enabled = False
        self.style_mimic_target = "c"

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
            "survey_open_days": self.survey_open_days,
            "group_chat_duration_minutes": self.group_chat_duration_minutes,
            "qualtrics_handoff_enabled": self.qualtrics_handoff_enabled,
            "qualtrics_store_chat": self.qualtrics_store_chat,
            "qualtrics_field_transcript": self.qualtrics_field_transcript,
            "qualtrics_field_status": self.qualtrics_field_status,
            "ai_starts_conversation": self.ai_starts_conversation,
            "turn_mode": self.turn_mode,
            "turn_duration_seconds": self.turn_duration_seconds,
            "assignment_mode": self.assignment_mode,
            "condition_enabled": self.condition_enabled,
            "style_mimic_enabled": self.style_mimic_enabled,
            "style_mimic_target": self.style_mimic_target,
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
        obj.survey_open_days = max(1, min(int(data.get("survey_open_days", 7)), 90))
        gcm = data.get("group_chat_duration_minutes")
        if gcm is not None:
            obj.group_chat_duration_minutes = max(1, min(int(gcm), 180))
        else:
            # Legacy group_timeout was inactivity minutes — default 5 min per-group chat
            obj.group_chat_duration_minutes = 5
        obj.qualtrics_handoff_enabled = data.get("qualtrics_handoff_enabled", False)
        obj.qualtrics_store_chat = data.get("qualtrics_store_chat", False)
        obj.qualtrics_field_transcript = data.get("qualtrics_field_transcript", "chat_transcript")
        obj.qualtrics_field_status = data.get("qualtrics_field_status", "chat_status")
        obj.ai_starts_conversation = data.get("ai_starts_conversation", False)
        obj.turn_mode = data.get("turn_mode", "none")
        obj.turn_duration_seconds = data.get("turn_duration_seconds", 60)
        obj.assignment_mode = data.get("assignment_mode", "fifo")
        obj.condition_enabled = bool(data.get("condition_enabled", True))
        obj.style_mimic_enabled = bool(data.get("style_mimic_enabled", False))
        obj.style_mimic_target = str(data.get("style_mimic_target") or "c").strip() or "c"
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
        survey_open_days: int = 7,
        group_chat_duration_minutes: int = 5,
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
        condition_enabled: bool = True,
        style_mimic_enabled: bool = False,
        style_mimic_target: str = "c",
    ) -> str:
        session_id = f"SES-{uuid.uuid4().hex[:5].upper()}"
        config = SessionConfig(session_id, name, group_size, bot_enabled)
        config.bots = bots
        config.survey_open_days = max(1, min(survey_open_days, 90))
        config.group_chat_duration_minutes = max(1, min(group_chat_duration_minutes, 180))
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
        config.condition_enabled = bool(condition_enabled)
        if config.condition_enabled:
            config.assignment_mode = "stratified"
        else:
            config.assignment_mode = assignment_mode if assignment_mode in ("fifo", "stratified") else "fifo"
        config.style_mimic_enabled = bool(style_mimic_enabled)
        config.style_mimic_target = (style_mimic_target or "c").strip() or "c"

        self.sessions[session_id] = config
        self.active_rooms[session_id] = {}
        self.queues[session_id] = []
        self.stratified_queues[session_id] = {}
        self.save_all_sessions()
        print(f"🎯 New Session Created: {session_id} ({name})")
        return session_id

    def get_session(self, session_id: str) -> Optional[SessionConfig]:
        return self.sessions.get(session_id)

    def is_session_open(self, session: SessionConfig) -> bool:
        """True while the session still accepts new participants (survey collection window)."""
        if not session:
            return False
        try:
            created = session.created_at
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
        except (TypeError, ValueError):
            created = datetime.now()
        deadline = created + timedelta(days=max(1, session.survey_open_days))
        return datetime.now() < deadline

    def session_to_admin_dict(self, session: SessionConfig) -> Dict:
        return session.to_dict()

    def update_session(self, session_id: str, data: Dict) -> bool:
        session = self.sessions.get(session_id)
        if not session:
            return False
        if "session_name" in data and data["session_name"]:
            session.name = str(data["session_name"]).strip()
        if "group_size" in data:
            session.group_size = max(1, int(data["group_size"]))
        if "bot_enabled" in data:
            session.bot_enabled = bool(data["bot_enabled"])
        if "bots" in data:
            session.bots = data["bots"]
        if "participant_names" in data:
            session.participant_names = data["participant_names"] or []
        if "spy_mode_enabled" in data:
            session.spy_mode_enabled = bool(data["spy_mode_enabled"])
        if "session_mode" in data:
            session.session_mode = int(data["session_mode"])
        if "survey_open_days" in data:
            session.survey_open_days = max(1, min(int(data["survey_open_days"]), 90))
        if "group_chat_duration_minutes" in data:
            session.group_chat_duration_minutes = max(1, min(int(data["group_chat_duration_minutes"]), 180))
        if "qualtrics_handoff_enabled" in data:
            session.qualtrics_handoff_enabled = bool(data["qualtrics_handoff_enabled"])
        if "qualtrics_store_chat" in data:
            session.qualtrics_store_chat = bool(data["qualtrics_store_chat"])
        if "qualtrics_field_transcript" in data:
            session.qualtrics_field_transcript = str(data["qualtrics_field_transcript"] or "chat_transcript")
        if "qualtrics_field_status" in data:
            session.qualtrics_field_status = str(data["qualtrics_field_status"] or "chat_status")
        if "ai_starts_conversation" in data:
            session.ai_starts_conversation = bool(data["ai_starts_conversation"])
        if "turn_mode" in data:
            tm = data["turn_mode"]
            session.turn_mode = tm if tm in ("none", "round_robin", "timed") else "none"
        if "turn_duration_seconds" in data:
            session.turn_duration_seconds = max(10, int(data["turn_duration_seconds"]))
        if "condition_enabled" in data:
            session.condition_enabled = bool(data["condition_enabled"])
        if "assignment_mode" in data:
            am = data["assignment_mode"]
            session.assignment_mode = am if am in ("fifo", "stratified") else "fifo"
        if getattr(session, "condition_enabled", True):
            session.assignment_mode = "stratified"
        if "style_mimic_enabled" in data:
            session.style_mimic_enabled = bool(data["style_mimic_enabled"])
        if "style_mimic_target" in data:
            t = str(data["style_mimic_target"] or "").strip()
            if t:
                session.style_mimic_target = t
        self.save_all_sessions()
        return True

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
                "survey_open_days": config.survey_open_days,
                "group_chat_duration_minutes": config.group_chat_duration_minutes,
                "is_open": self.is_session_open(config),
            })
        return summary

    def _normalize_condition(self, condition: Optional[str]) -> str:
        c = (condition or "").strip()
        return c if c else "_default"

    def add_to_queue(self, session_id: str, uid: str, condition: Optional[str] = None) -> Optional[str]:
        if session_id not in self.sessions:
            print(f"⚠️ Warning: Attempted to queue for invalid session {session_id}")
            return None

        session_config = self.sessions[session_id]
        if not self.is_session_open(session_config):
            print(f"🚫 Session {session_id} is closed (survey collection ended).")
            return None

        if not getattr(session_config, "condition_enabled", True):
            condition = None

        if uid in self.user_locations:
            return self.user_locations[uid].get("group_id")

        if getattr(session_config, "condition_enabled", True):
            return self._add_to_stratified_queue(session_id, uid, condition, session_config)
        if session_config.assignment_mode == "stratified":
            return self._add_to_stratified_queue(session_id, uid, condition, session_config)
        return self._add_to_fifo_queue(session_id, uid, session_config)

    def _add_to_fifo_queue(
        self, session_id: str, uid: str, session_config: SessionConfig,
    ) -> Optional[str]:
        queue = self.queues[session_id]
        if uid not in queue:
            queue.append(uid)
            print(f"⏳ {uid} joined FIFO queue for [{session_id}]. (size: {len(queue)})")

        if len(queue) >= session_config.group_size:
            matched_members = queue[: session_config.group_size]
            self.queues[session_id] = queue[session_config.group_size :]
            group_id = f"GRP-{uuid.uuid4().hex[:4].upper()}"
            self.create_group(session_id, group_id, matched_members, condition=None)
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
            session_config = self.sessions.get(session_id)
            group_info = {
                "members": members if members else [],
                "created_at": now,
                "last_activity": now,
                "condition": self._normalize_condition(condition) if condition else None,
                "opening_sent": False,
                "turn_initialized": False,
            }
            if session_config and session_config.bots and getattr(session_config, "condition_enabled", True):
                assign_group_disclosure(session_config.bots, condition, group_info)
            self.active_rooms[session_id][group_id] = group_info
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
