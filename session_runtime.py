"""
Runtime helpers: turn-taking, AI opening, Qualtrics session end, participant export.
"""

import asyncio
import json
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from match_manager import match_manager, SessionConfig
from context_manager import get_or_create_context, get_context
from bot_manager import get_or_create_bot
from db.database import get_room_history, save_message
from cache_manager import cache_manager
from activity_logger import activity_logger

turn_timer_tasks: Dict[str, asyncio.Task] = {}


def get_bot_names(session: SessionConfig) -> Set[str]:
    return {b.get("name", "").strip() for b in (session.bots or []) if b.get("name")}


def get_human_display_names(session: SessionConfig, group_info: Dict) -> List[str]:
    bot_names = get_bot_names(session)
    names = []
    for uid in group_info.get("members", []):
        dn = group_info.get("member_names", {}).get(uid, uid)
        if dn not in bot_names:
            names.append(dn)
    return names


def turn_payload(session: SessionConfig, group_info: Dict) -> Dict:
    mode = session.turn_mode
    if mode == "none":
        return {"type": "turn_update", "turn_mode": "none", "can_speak": True}
    order = group_info.get("turn_order", [])
    idx = group_info.get("turn_index", 0) % max(len(order), 1)
    current = order[idx] if order else None
    remaining = None
    if mode == "timed" and group_info.get("turn_deadline"):
        remaining = max(0, int(group_info["turn_deadline"] - datetime.now().timestamp()))
    return {
        "type": "turn_update",
        "turn_mode": mode,
        "current_speaker": current,
        "turn_order": order,
        "can_speak": True,
        "seconds_remaining": remaining,
    }


def can_human_speak(display_name: str, session: SessionConfig, group_info: Dict) -> bool:
    if session.turn_mode == "none":
        return True
    order = group_info.get("turn_order", [])
    if not order:
        return True
    idx = group_info.get("turn_index", 0) % len(order)
    return order[idx] == display_name


def init_turn_state(session: SessionConfig, group_info: Dict):
    if session.turn_mode == "none" or group_info.get("turn_initialized"):
        return
    humans = get_human_display_names(session, group_info)
    if not humans:
        return
    group_info["turn_order"] = humans
    group_info["turn_index"] = 0
    group_info["turn_initialized"] = True
    if session.turn_mode == "timed":
        group_info["turn_deadline"] = datetime.now().timestamp() + session.turn_duration_seconds


def _iter_connections(group_info: Dict):
    for entry in group_info.get("connections", []):
        ws = entry.get("websocket")
        uid = entry.get("uid")
        if ws is not None and uid:
            yield uid, ws
    for ws in group_info.get("ws_connections", []):
        yield None, ws


async def broadcast_turn(session_id: str, group_id: str, broadcast_fn: Callable):
    session = match_manager.get_session(session_id)
    group_info = match_manager.get_group_info(session_id, group_id)
    if not session or not group_info:
        return
    base = turn_payload(session, group_info)
    order = group_info.get("turn_order", [])
    idx = group_info.get("turn_index", 0) % max(len(order), 1)
    current = order[idx] if order else None
    names = group_info.get("member_names", {})
    for uid, conn in _iter_connections(group_info):
        dn = names.get(uid, uid) if uid else None
        can = base["turn_mode"] == "none" or (dn and dn == current)
        p = {**base, "can_speak": can}
        try:
            await conn.send_text(json.dumps(p))
        except Exception:
            pass


async def advance_turn(session_id: str, group_id: str, broadcast_fn: Callable):
    session = match_manager.get_session(session_id)
    group_info = match_manager.get_group_info(session_id, group_id)
    if not session or not group_info or session.turn_mode == "none":
        return
    order = group_info.get("turn_order", [])
    if not order:
        return
    group_info["turn_index"] = (group_info.get("turn_index", 0) + 1) % len(order)
    if session.turn_mode == "timed":
        group_info["turn_deadline"] = datetime.now().timestamp() + session.turn_duration_seconds
        schedule_timed_turn(session_id, group_id, broadcast_fn, session.turn_duration_seconds)
    await broadcast_turn(session_id, group_id, broadcast_fn)


def schedule_timed_turn(session_id: str, group_id: str, broadcast_fn: Callable, seconds: int):
    key = f"{session_id}_{group_id}"
    if key in turn_timer_tasks:
        t = turn_timer_tasks.pop(key)
        if not t.done():
            t.cancel()

    async def _tick():
        try:
            await asyncio.sleep(seconds)
            await advance_turn(session_id, group_id, broadcast_fn)
        except asyncio.CancelledError:
            pass

    turn_timer_tasks[key] = asyncio.create_task(_tick())


def cancel_turn_timer(session_id: str, group_id: str):
    key = f"{session_id}_{group_id}"
    if key in turn_timer_tasks:
        t = turn_timer_tasks.pop(key)
        if not t.done():
            t.cancel()


async def build_transcript_text(group_id: str) -> str:
    messages = await get_room_history(group_id, limit=5000)
    lines = []
    for m in messages:
        ts = m.get("timestamp", "")
        lines.append(f"[{ts}] {m.get('sender', '?')}: {m.get('text', '')}")
    return "\n".join(lines)


async def build_participant_export(session_id: str, participant_id: str) -> Dict:
    group_id = match_manager.get_participant_group_id(session_id, participant_id)
    if not group_id:
        return {
            "session_id": session_id,
            "participant_id": participant_id,
            "group_id": None,
            "messages": [],
            "transcript_text": "",
        }
    messages = await get_room_history(group_id, limit=5000)
    group_info = match_manager.get_group_info(session_id, group_id) or {}
    display_name = group_info.get("member_names", {}).get(participant_id, participant_id)
    return {
        "session_id": session_id,
        "participant_id": participant_id,
        "group_id": group_id,
        "display_name": display_name,
        "messages": messages,
        "transcript_text": await build_transcript_text(group_id),
    }


async def notify_session_ended(session_id: str, group_id: str, reason: str):
    """Send session_ended to each connection (personalized transcript when enabled)."""
    session = match_manager.get_session(session_id)
    group_info = match_manager.get_group_info(session_id, group_id) or {}
    cancel_turn_timer(session_id, group_id)

    base = {
        "type": "session_ended",
        "reason": reason,
        "message": "This chat session has ended.",
        "qualtrics_handoff": bool(session and session.qualtrics_handoff_enabled),
        "qualtrics_store_chat": bool(session and session.qualtrics_store_chat),
        "qualtrics_field_transcript": getattr(session, "qualtrics_field_transcript", "chat_transcript"),
        "qualtrics_field_status": getattr(session, "qualtrics_field_status", "chat_status"),
    }

    sent = set()
    for uid, conn in _iter_connections(group_info):
        if id(conn) in sent:
            continue
        sent.add(id(conn))
        payload = {**base, "participant_id": uid}
        if session and session.qualtrics_store_chat and uid:
            export = await build_participant_export(session_id, uid)
            payload["transcript_text"] = export.get("transcript_text", "")
            payload["transcript_json"] = json.dumps(export.get("messages", []))
        try:
            await conn.send_text(json.dumps(payload))
        except Exception:
            pass


async def maybe_trigger_ai_opening(
    session_id: str,
    group_id: str,
    broadcast_fn: Callable,
    process_opening_fn: Callable,
):
    """First human connected + empty history → optional AI opener."""
    session = match_manager.get_session(session_id)
    group_info = match_manager.get_group_info(session_id, group_id)
    if not session or not group_info:
        return
    if not session.ai_starts_conversation or not session.bot_enabled or not session.bots:
        return
    if group_info.get("opening_sent"):
        return
    history = await get_room_history(group_id, limit=1)
    if history:
        group_info["opening_sent"] = True
        return

    group_info["opening_sent"] = True
    bot_cfg = session.bots[0]
    bot_name = bot_cfg.get("name", "Assistant")
    await process_opening_fn(session_id, group_id, bot_cfg, bot_name)


async def send_ai_opening_message(session_id: str, group_id: str, bot_cfg: Dict, bot_name: str, broadcast_fn: Callable):
    get_or_create_context(group_id)
    ctx = get_context(group_id)
    bot = get_or_create_bot(group_id, bot_name, bot_cfg.get("prompt", ""))
    opening_prompt = (
        "[The conversation is just starting. You speak first. "
        "Greet the group naturally and invite discussion based on your persona.]"
    )
    reply = await bot.generate_response(
        "system",
        opening_prompt,
        "",
        max_tokens=bot_cfg.get("max_tokens", 200),
        temperature=bot_cfg.get("temperature", 0.7),
    )
    if not reply:
        return
    cache_manager.cache_message(group_id, bot.name, reply)
    await save_message(group_id, bot.name, reply)
    if ctx:
        ctx.add_message(bot.name, reply)
    activity_logger.log_bot_response(session_id, group_id, bot.name, reply, bot_cfg.get("mode", 1))
    await broadcast_fn(session_id, group_id, {"type": "message", "sender": bot.name, "text": reply})
