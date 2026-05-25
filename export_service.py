"""
Export Service: Data export (CSV) and log downloads.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from io import BytesIO, StringIO
import csv


class ExportService:
    """
    Export service:
    - CSV export (Session data, Room data, messages, etc.)
    - Activity log export
    - Statistics report generation
    """

    def __init__(self, export_dir: str = "exports"):
        self.export_dir = export_dir
        os.makedirs(export_dir, exist_ok=True)

    # ==================== CSV Helpers ====================

    def _make_csv_buffer(self) -> tuple:
        """Returns (StringIO buffer, csv.writer) pair."""
        buf = StringIO()
        return buf, csv.writer(buf)

    def _finalize_csv(self, buf: StringIO) -> BytesIO:
        """Encodes StringIO content to UTF-8 BytesIO for HTTP streaming."""
        return BytesIO(buf.getvalue().encode('utf-8'))

    # ==================== CSV Export ====================

    def export_session_data_csv(self, session_id: str, session_manager,
                                room_data: Dict) -> BytesIO:
        """Export all Session data as CSV: session info, room list, message stats."""
        buf, writer = self._make_csv_buffer()

        session = session_manager.get_session(session_id)
        if not session:
            return self._finalize_csv(buf)

        writer.writerow(["Session Information"])
        writer.writerow(["Session ID", session.session_id])
        writer.writerow(["Session Name", getattr(session, 'session_name', getattr(session, 'name', ''))])
        writer.writerow(["Status", getattr(session, 'status', '')])
        writer.writerow(["Created At", session.created_at])
        writer.writerow(["Bot Enabled", session.bot_enabled])
        writer.writerow([])

        writer.writerow(["Bot Configuration"])
        writer.writerow(["Bot Name", "Mode", "Delay (s)", "Typing CPS", "Idle Threshold"])
        for bot in session.bots:
            writer.writerow([
                bot.get("name", ""),
                bot.get("mode", 1),
                bot.get("delay_seconds", 0),
                bot.get("typing_cps", 12),
                bot.get("idle_threshold", 20)
            ])
        writer.writerow([])

        writer.writerow(["Room Data"])
        writer.writerow(["Room ID", "Participant ID", "Created At", "Status", "Message Count"])

        rooms = list(session_manager.active_rooms.get(session_id, {}).keys())
        for room_id in rooms:
            group_info = session_manager.get_group_info(session_id, room_id)
            members = group_info.get("members", []) if group_info else []
            created_at = group_info.get("created_at", "") if group_info else ""
            writer.writerow([
                room_id,
                ", ".join(members),
                created_at,
                "active",
                len(room_data.get(room_id, []))
            ])
        writer.writerow([])

        writer.writerow(["Message Summary"])
        writer.writerow(["Room ID", "Members", "Total Messages"])
        for room_id in rooms:
            if room_id in room_data:
                group_info = session_manager.get_group_info(session_id, room_id)
                members = group_info.get("members", []) if group_info else []
                writer.writerow([room_id, ", ".join(members), len(room_data[room_id])])

        return self._finalize_csv(buf)

    def export_room_messages_csv(self, room_id: str, messages: List[Dict]) -> BytesIO:
        """Export all messages from a single Room."""
        buf, writer = self._make_csv_buffer()

        writer.writerow(["Room ID", room_id])
        writer.writerow(["Export Time", datetime.now().isoformat()])
        writer.writerow([])

        writer.writerow(["Sender", "Message", "Timestamp"])
        for msg in messages:
            writer.writerow([
                msg.get("sender", ""),
                msg.get("text", ""),
                msg.get("timestamp", "")
            ])

        return self._finalize_csv(buf)

    def export_activity_log_csv(self, session_id: str, activity_logs: List[Dict]) -> BytesIO:
        """Export Activity log as CSV."""
        buf, writer = self._make_csv_buffer()

        writer.writerow(["Session Activity Log"])
        writer.writerow(["Session ID", session_id])
        writer.writerow(["Export Time", datetime.now().isoformat()])
        writer.writerow([])

        writer.writerow(["Timestamp", "Event Type", "Room ID", "User/Bot", "Details"])
        for log in activity_logs:
            writer.writerow([
                log.get("timestamp", ""),
                log.get("event_type", ""),
                log.get("room_id", ""),
                log.get("actor", ""),
                log.get("details", "")
            ])

        return self._finalize_csv(buf)

    # ==================== JSON Export ====================

    def export_session_as_json(self, session_id: str, session_manager,
                               room_data: Dict) -> Dict:
        """Export Session as JSON for downstream processing."""
        session = session_manager.get_session(session_id)
        if not session:
            return {}

        rooms = list(session_manager.active_rooms.get(session_id, {}).keys())

        data = {
            "session": {
                "id": session.session_id,
                "name": getattr(session, 'session_name', getattr(session, 'name', '')),
                "created_at": str(session.created_at),
                "bot_config": session.bots
            },
            "rooms": [],
            "messages_by_room": {}
        }

        for room_id in rooms:
            group_info = session_manager.get_group_info(session_id, room_id)
            members = group_info.get("members", []) if group_info else []
            created_at = str(group_info.get("created_at", "")) if group_info else ""
            data["rooms"].append({
                "id": room_id,
                "members": members,
                "created_at": created_at,
                "message_count": len(room_data.get(room_id, []))
            })
            if room_id in room_data:
                data["messages_by_room"][room_id] = room_data[room_id]

        return data

    def save_exported_data(self, filename: str, data: Dict) -> str:
        """Save exported data to a file."""
        filepath = os.path.join(self.export_dir, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"✅ Data exported: {filepath}")
            return filepath
        except Exception as e:
            print(f"❌ Export failed: {e}")
            return ""

    # ==================== Statistics Report ====================

    def generate_session_report(self, session_id: str, session_manager) -> Dict:
        """Generate a Session statistics report."""
        session = session_manager.get_session(session_id)
        if not session:
            return {}

        stats = session_manager.get_session_stats(session_id) if hasattr(session_manager, 'get_session_stats') else {}
        rooms = session_manager.get_session_rooms(session_id) if hasattr(session_manager, 'get_session_rooms') else []

        return {
            "title": f"Session Report - {getattr(session, 'session_name', getattr(session, 'name', ''))}",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "session_id": session.session_id,
                "session_name": getattr(session, 'session_name', getattr(session, 'name', '')),
                "total_rooms": len(rooms),
                "total_messages": stats.get("total_messages", 0),
                "status": getattr(session, 'status', '')
            },
            "bots": session.bots,
            "rooms_details": [
                {
                    "room_id": room.room_id,
                    "participant_id": room.participant_id,
                    "messages": room.message_count
                }
                for room in rooms
            ]
        }

    # ==================== Log Export ====================

    def export_error_logs(self, error_logs: List[Dict]) -> BytesIO:
        """Export error logs as CSV."""
        buf, writer = self._make_csv_buffer()

        writer.writerow(["Error ID", "Timestamp", "Context", "Severity", "Message"])
        for log in error_logs:
            writer.writerow([
                log.get("error_id", ""),
                log.get("timestamp", ""),
                log.get("context", ""),
                log.get("severity", ""),
                log.get("message", "")
            ])

        return self._finalize_csv(buf)

    def export_activity_timeline(self, activity_logs: List[Dict]) -> BytesIO:
        """Export Activity timeline as CSV."""
        buf, writer = self._make_csv_buffer()

        sorted_logs = sorted(activity_logs, key=lambda x: x.get("timestamp", ""))

        writer.writerow(["Activity Timeline"])
        writer.writerow(["Timestamp", "Event", "Details"])

        for log in sorted_logs:
            writer.writerow([
                log.get("timestamp", ""),
                log.get("event_type", ""),
                json.dumps(log.get("details", {}))
            ])

        return self._finalize_csv(buf)


# Global instance
export_service = ExportService()
