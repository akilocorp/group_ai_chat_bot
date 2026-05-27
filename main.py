"""
Main Application: Session Management, Caching, Queueing, Logging, and Exporting.
Supports Qualtrics embedding and isolated Multi-Session/Multi-Group management.
"""

import asyncio
import os
import uuid
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# ============ Internal Modules ============
from match_manager import match_manager, SessionConfig
from context_manager import get_or_create_context, get_context
from bot_manager import analyze_intent, get_or_create_bot, get_or_create_bot_from_cfg, remove_room_bots

# Database Functions
from db.database import save_message, get_room_history

# ============ Optimization Modules ============
from cache_manager import cache_manager
from bot_queue import bot_response_queue, BotResponse
from error_handler import error_handler, ErrorSeverity
from activity_logger import activity_logger, ActivityType
from export_service import export_service
from session_runtime import (
    can_human_speak,
    init_turn_state,
    advance_turn,
    broadcast_turn,
    maybe_trigger_ai_opening,
    send_ai_opening_message,
    notify_session_ended,
    build_participant_export,
    cancel_turn_timer,
    schedule_timed_turn,
)

load_dotenv()

# ============ Initialization ============
app = FastAPI(title="Hybrid AI Chat System with Session Management")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="templates")

Path("static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Per-group orchestration utilities
group_locks: Dict[str, asyncio.Lock] = {}
group_idle_tasks: Dict[str, asyncio.Task] = {}
DEFAULT_IDLE_THRESHOLD = 20

def get_group_lock(group_id: str) -> asyncio.Lock:
    if group_id not in group_locks:
        group_locks[group_id] = asyncio.Lock()
    return group_locks[group_id]


def touch_group_activity(session_id: str, group_id: str):
    """Updates last_activity timestamp for group timeout enforcement."""
    group_info = match_manager.get_group_info(session_id, group_id)
    if group_info is not None:
        group_info["last_activity"] = datetime.now()


async def group_timeout_watcher():
    """Ends each group chat after group_chat_duration_minutes from group formation."""
    while True:
        await asyncio.sleep(15)
        now = datetime.now()
        for session_id, groups in list(match_manager.active_rooms.items()):
            session = match_manager.get_session(session_id)
            if not session:
                continue
            duration_seconds = max(1, session.group_chat_duration_minutes) * 60
            for group_id, group_info in list(groups.items()):
                started = group_info.get("created_at")
                if not started:
                    continue
                if isinstance(started, str):
                    try:
                        started = datetime.fromisoformat(started)
                    except ValueError:
                        continue
                if (now - started).total_seconds() >= duration_seconds:
                    await notify_session_ended(session_id, group_id, "duration_limit")
                    for entry in list(group_info.get("connections", [])):
                        try:
                            await entry["websocket"].close()
                        except Exception:
                            pass
                    for conn in list(group_info.get("ws_connections", [])):
                        try:
                            await conn.close()
                        except Exception:
                            pass
                    match_manager.end_group(session_id, group_id)
                    print(
                        f"⏱️ Group {group_id} closed after {session.group_chat_duration_minutes}m chat duration"
                    )

async def broadcast(session_id: str, group_id: str, payload):
    """Broadcasts a JSON message to all connections in a specific small group."""
    group_info = match_manager.get_group_info(session_id, group_id)
    if not group_info:
        return

    conns = group_info.get("ws_connections", [])
    if not conns:
        return

    message = json.dumps(payload) if isinstance(payload, dict) else str(payload)

    await asyncio.gather(
        *[conn.send_text(message) for conn in conns],
        return_exceptions=True
    )


async def _ai_opening_wrapper(session_id: str, group_id: str, bot_cfg: Dict, bot_name: str):
    await send_ai_opening_message(session_id, group_id, bot_cfg, bot_name, broadcast)


def reset_idle_timer(session_id: str, group_id: str, idle_seconds: int = DEFAULT_IDLE_THRESHOLD):
    """Resets the idle timer for bot auto-initiation within a group."""
    task_key = f"{session_id}_{group_id}"

    if task_key in group_idle_tasks:
        task = group_idle_tasks[task_key]
        if not task.done():
            task.cancel()

    async def idle_watcher():
        try:
            await asyncio.sleep(idle_seconds)
        except asyncio.CancelledError:
            return

        session_cfg = match_manager.get_session(session_id)
        if not session_cfg or not session_cfg.bot_enabled or not session_cfg.bots:
            return

        ctx = get_context(group_id)
        if not ctx:
            return

        initiator_cfg = random.choice(session_cfg.bots)
        gi = match_manager.get_group_info(session_id, group_id) or {}
        initiator = get_or_create_bot_from_cfg(group_id, initiator_cfg, gi)
        summary = ctx.get_context_summary(num_messages=initiator_cfg.get('context_messages', 20))

        session_cfg = match_manager.get_session(session_id)
        peer_names = [
            b["name"] for b in (session_cfg.bots if session_cfg else [])
            if b.get("name") and b["name"] != initiator.name
        ]
        init_prompt = (
            "[Chat went quiet. Send ONE casual line (max 2 short sentences) "
            "to nudge the group—no lists, no 'hello team'.]"
        )
        reply = await initiator.generate_response(
            "system", init_prompt, summary,
            max_tokens=initiator_cfg.get('max_tokens', 60),
            temperature=initiator_cfg.get('temperature', 0.75),
            peer_names=peer_names,
            max_words=initiator_cfg.get("max_words", 45),
        )

        if reply:
            cache_manager.cache_message(group_id, initiator.name, reply)
            await save_message(group_id, initiator.name, reply)
            ctx.add_message(initiator.name, reply)
            activity_logger.log_bot_response(session_id, group_id, initiator.name, reply, initiator_cfg.get("mode", 1))
            await broadcast(session_id, group_id, {"type": "message", "sender": initiator.name, "text": reply})
            touch_group_activity(session_id, group_id)

        reset_idle_timer(session_id, group_id, initiator_cfg.get("idle_threshold", DEFAULT_IDLE_THRESHOLD))

    group_idle_tasks[task_key] = asyncio.create_task(idle_watcher())


# ============ Page Routes ============

def check_auth(request: Request):
    """Check if user is authenticated via session cookie or header."""
    # Check sessionStorage equivalent via cookie
    auth_cookie = request.cookies.get("actr_auth")
    if auth_cookie == "authenticated":
        return True
    return False

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if not check_auth(request):
        return templates.TemplateResponse("login.html", {"request": request})
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/wait", response_class=HTMLResponse)
async def wait_page(request: Request):
    if not check_auth(request):
        return templates.TemplateResponse("login.html", {"request": request})
    return templates.TemplateResponse("wait.html", {"request": request})

@app.get("/chat/{session_id}/{group_id}", response_class=HTMLResponse)
async def chat_page(request: Request, session_id: str, group_id: str):
    if not check_auth(request):
        return templates.TemplateResponse("login.html", {"request": request})
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "session_id": session_id,
        "group_id": group_id
    })

@app.get("/embed.html", response_class=HTMLResponse)
async def embed_page(request: Request):
    return templates.TemplateResponse("embed.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not check_auth(request):
        return templates.TemplateResponse("login.html", {"request": request})
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Legacy URL — unified dashboard lives at /."""
    return RedirectResponse(url="/", status_code=302)

@app.get("/manual", response_class=HTMLResponse)
async def manual_page(request: Request):
    if not check_auth(request):
        return templates.TemplateResponse("login.html", {"request": request})
    return templates.TemplateResponse("manual.html", {"request": request})

@app.get("/join", response_class=HTMLResponse)
async def join_page(request: Request):
    return templates.TemplateResponse("join.html", {"request": request})

@app.get("/api/groups/{session_id}/{group_id}/info")
async def get_group_info_api(session_id: str, group_id: str):
    """Returns group info including member names for join page."""
    group_info = match_manager.get_group_info(session_id, group_id)
    if not group_info:
        return {"member_names": {}, "members": []}
    return {
        "member_names": group_info.get("member_names", {}),
        "members": group_info.get("members", [])
    }


# ============ Session Management API ============

class SessionCreateRequest(BaseModel):
    session_name: str
    group_size: int
    bot_enabled: bool
    bots: List[Dict]
    participant_names: Optional[List[str]] = None
    spy_mode_enabled: bool = False
    session_mode: int = 1
    survey_open_days: int = 7
    group_chat_duration_minutes: int = 5
    qualtrics_handoff_enabled: bool = True
    qualtrics_store_chat: bool = True
    qualtrics_field_transcript: str = "transcript"
    qualtrics_field_status: str = "chat_status"
    ai_starts_conversation: bool = False
    turn_mode: str = "none"
    turn_duration_seconds: int = 60
    assignment_mode: str = "fifo"

@app.get("/api/sessions")
async def list_sessions():
    """Returns a summary of all sessions for the Admin Dashboard and Lobby."""
    return {"sessions": match_manager.get_all_sessions_summary()}

@app.post("/api/sessions/create")
async def create_session(data: SessionCreateRequest):
    """Creates a new Session via Admin Dashboard."""
    try:
        cleaned_bots = []
        for bot in data.bots:
            name = (bot.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="Each bot must have a non-empty name")
            cleaned_bots.append({**bot, "name": name})

        session_id = match_manager.create_session(
            name=data.session_name,
            group_size=data.group_size,
            bot_enabled=data.bot_enabled,
            bots=cleaned_bots,
            survey_open_days=data.survey_open_days,
            group_chat_duration_minutes=data.group_chat_duration_minutes,
            participant_names=data.participant_names,
            spy_mode_enabled=data.spy_mode_enabled,
            session_mode=data.session_mode,
            qualtrics_handoff_enabled=data.qualtrics_handoff_enabled,
            qualtrics_store_chat=data.qualtrics_store_chat,
            qualtrics_field_transcript=data.qualtrics_field_transcript,
            qualtrics_field_status=data.qualtrics_field_status,
            ai_starts_conversation=data.ai_starts_conversation,
            turn_mode=data.turn_mode,
            turn_duration_seconds=data.turn_duration_seconds,
            assignment_mode=data.assignment_mode,
        )
        activity_logger.log_session_started(session_id, data.session_name)
        return {"status": "success", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        error_id = error_handler.handle_exception(e, "create_session")
        return {"status": "error", "message": str(e), "error_id": error_id}

@app.get("/api/sessions/{session_id}/config")
async def get_session_config(
    session_id: str,
    participant_id: Optional[str] = Query(None),
    condition: Optional[str] = Query(None),
):
    """Fetches Session Configuration (used by chat.html / embed)."""
    from study_conditions import apply_disclosure_to_bots, assign_group_disclosure, resolve_ai_disclosed_bot

    session = match_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    bots = list(session.bots)
    ai_disclosed_bot = None
    study_condition = None

    if participant_id and participant_id in match_manager.user_locations:
        loc = match_manager.user_locations[participant_id]
        if loc.get("session_id") == session_id:
            gid = loc.get("group_id")
            group_info = match_manager.get_group_info(session_id, gid)
            if group_info:
                if "ai_disclosed_bot" not in group_info and session.bots:
                    assign_group_disclosure(session.bots, group_info.get("condition") or condition, group_info)
                ai_disclosed_bot = group_info.get("ai_disclosed_bot")
                study_condition = group_info.get("study_condition")
                bots = apply_disclosure_to_bots(session.bots, ai_disclosed_bot)
    elif condition and session.bots:
        ai_disclosed_bot, study_condition = resolve_ai_disclosed_bot(session.bots, condition)
        bots = apply_disclosure_to_bots(session.bots, ai_disclosed_bot)

    return {
        "session_id": session.session_id,
        "session_name": session.name,
        "bot_enabled": session.bot_enabled,
        "bots": bots,
        "ai_disclosed_bot": ai_disclosed_bot,
        "study_condition": study_condition,
        "group_size": session.group_size,
        "participant_names": session.participant_names,
        "spy_mode_enabled": session.spy_mode_enabled,
        "session_mode": session.session_mode,
        "qualtrics_handoff_enabled": session.qualtrics_handoff_enabled,
        "qualtrics_store_chat": session.qualtrics_store_chat,
        "qualtrics_enabled": bool(session.qualtrics_handoff_enabled and session.qualtrics_store_chat),
        "qualtrics_field_transcript": session.qualtrics_field_transcript,
        "ai_starts_conversation": session.ai_starts_conversation,
        "turn_mode": session.turn_mode,
        "turn_duration_seconds": session.turn_duration_seconds,
        "assignment_mode": session.assignment_mode,
        "survey_open_days": session.survey_open_days,
        "group_chat_duration_minutes": session.group_chat_duration_minutes,
    }


class SessionUpdateRequest(BaseModel):
    session_name: Optional[str] = None
    group_size: Optional[int] = None
    bot_enabled: Optional[bool] = None
    bots: Optional[List[Dict]] = None
    participant_names: Optional[List[str]] = None
    spy_mode_enabled: Optional[bool] = None
    session_mode: Optional[int] = None
    survey_open_days: Optional[int] = None
    group_chat_duration_minutes: Optional[int] = None
    qualtrics_handoff_enabled: Optional[bool] = None
    qualtrics_store_chat: Optional[bool] = None
    qualtrics_field_transcript: Optional[str] = None
    qualtrics_field_status: Optional[str] = None
    ai_starts_conversation: Optional[bool] = None
    turn_mode: Optional[str] = None
    turn_duration_seconds: Optional[int] = None
    assignment_mode: Optional[str] = None


@app.get("/api/sessions/{session_id}/admin")
async def get_session_admin_detail(session_id: str):
    """Full session config for Admin read-only view and modify."""
    session = match_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    data = match_manager.session_to_admin_dict(session)
    data["is_open"] = match_manager.is_session_open(session)
    try:
        created = session.created_at
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        data["survey_closes_at"] = (created + timedelta(days=session.survey_open_days)).isoformat()
    except (TypeError, ValueError):
        data["survey_closes_at"] = None
    return data


@app.put("/api/sessions/{session_id}")
async def modify_session(session_id: str, data: SessionUpdateRequest):
    """Update an existing session configuration (Admin modify)."""
    if session_id not in match_manager.sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        payload = data.model_dump(exclude_unset=True)
        if "bots" in payload and payload["bots"] is not None:
            cleaned = []
            for bot in payload["bots"]:
                name = (bot.get("name") or "").strip()
                if not name:
                    raise HTTPException(status_code=400, detail="Each bot must have a non-empty name")
                cleaned.append({**bot, "name": name})
            payload["bots"] = cleaned
        if not match_manager.update_session(session_id, payload):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "success", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        error_id = error_handler.handle_exception(e, "modify_session")
        return {"status": "error", "message": str(e), "error_id": error_id}


@app.get("/api/export/participant/{session_id}/{participant_id}")
async def export_participant_chat(session_id: str, participant_id: str):
    """
    Pull chat transcript for a participant (Qualtrics piped text, web services, or research export).
    """
    data = await build_participant_export(session_id, participant_id)
    if not data.get("group_id"):
        raise HTTPException(status_code=404, detail="No chat found for this participant in this session")
    return data

@app.get("/api/sessions/{session_id}/activity")
async def get_session_activity(session_id: str, limit: int = 100):
    """Fetches recent activity logs for a session."""
    activities = activity_logger.get_recent_activities(session_id, limit=limit)
    return {"session_id": session_id, "total_activities": len(activities), "activities": activities}


# ============ Admin Dashboard API ============

@app.get("/api/admin/rooms")
async def admin_get_rooms():
    """Returns all active rooms across all sessions for the Dashboard."""
    rooms = []
    for session_summary in match_manager.get_all_sessions_summary():
        sid = session_summary["id"]
        for group_id in session_summary.get("groups", []):
            group_info = match_manager.get_group_info(sid, group_id)
            if group_info:
                history = await get_room_history(group_id, limit=1000)
                rooms.append({
                    "id": group_id,
                    "session_id": sid,
                    "session_name": session_summary["name"],
                    "created_at": group_info.get("created_at", datetime.now()).isoformat()
                        if hasattr(group_info.get("created_at"), "isoformat")
                        else str(group_info.get("created_at", "")),
                    "participants": group_info.get("members", []),
                    "message_count": len(history)
                })

    # Determine bot_enabled from any active session
    bot_enabled = any(
        match_manager.get_session(s["id"]).bot_enabled
        for s in match_manager.get_all_sessions_summary()
        if match_manager.get_session(s["id"])
    )

    # Count waiting users across all queues
    waiting_count = sum(len(q) for q in match_manager.queues.values())

    return {
        "rooms": rooms,
        "waiting_count": waiting_count,
        "bot_enabled": bot_enabled
    }

@app.get("/api/admin/config")
async def admin_get_config():
    """Returns bot config from the first active session (used by dashboard)."""
    for summary in match_manager.get_all_sessions_summary():
        session = match_manager.get_session(summary["id"])
        if session and session.bot_enabled:
            return {"bots": session.bots, "bot_enabled": True}
    return {"bots": [], "bot_enabled": False}

@app.get("/api/admin/rooms/{room_id}/messages")
async def admin_get_room_messages(room_id: str):
    """Returns message history for a specific room (used by dashboard Live Feed)."""
    messages = await get_room_history(room_id, limit=200)
    return {"messages": messages}

@app.post("/api/admin/rooms/{room_id}/pause")
async def admin_pause_room(room_id: str):
    """Pause a room (prevent new messages from being processed)."""
    try:
        # Find which session this room belongs to
        for session_id, groups in match_manager.active_rooms.items():
            if room_id in groups:
                group_info = groups[room_id]
                group_info["paused"] = True
                return {"status": "success", "message": f"Room {room_id} paused"}
        return {"status": "error", "message": "Room not found"}
    except Exception as e:
        error_id = error_handler.handle_exception(e, "admin_pause_room")
        return {"status": "error", "message": str(e), "error_id": error_id}

@app.delete("/api/admin/rooms/{room_id}")
async def admin_delete_room(room_id: str):
    """Delete a room and all its data."""
    try:
        from db.database import delete_room_data
        # Find which session this room belongs to
        for session_id, groups in match_manager.active_rooms.items():
            if room_id in groups:
                match_manager.end_group(session_id, room_id)
                await delete_room_data(room_id)
                cache_manager.invalidate_summary(room_id)
                remove_room_bots(room_id)
                return {"status": "success", "message": f"Room {room_id} deleted"}
        return {"status": "error", "message": "Room not found"}
    except Exception as e:
        error_id = error_handler.handle_exception(e, "admin_delete_room")
        return {"status": "error", "message": str(e), "error_id": error_id}

@app.delete("/api/admin/sessions/{session_id}")
async def admin_delete_session(session_id: str):
    """Delete a session and all its rooms."""
    try:
        from db.database import delete_room_data
        if session_id not in match_manager.sessions:
            return {"status": "error", "message": "Session not found"}

        # Delete all rooms in this session
        if session_id in match_manager.active_rooms:
            for group_id in list(match_manager.active_rooms[session_id].keys()):
                match_manager.end_group(session_id, group_id)
                await delete_room_data(group_id)
                cache_manager.invalidate_summary(group_id)
                remove_room_bots(group_id)

        # Remove session
        del match_manager.sessions[session_id]
        if session_id in match_manager.active_rooms:
            del match_manager.active_rooms[session_id]
        if session_id in match_manager.queues:
            del match_manager.queues[session_id]

        match_manager.save_all_sessions()
        return {"status": "success", "message": f"Session {session_id} deleted"}
    except Exception as e:
        error_id = error_handler.handle_exception(e, "admin_delete_session")
        return {"status": "error", "message": str(e), "error_id": error_id}

@app.get("/api/export/session/{session_id}/activity")
async def export_session_activity(session_id: str):
    """Export full activity log for a session as CSV download, with session settings header."""
    import csv
    from io import StringIO, BytesIO
    buf = StringIO()
    writer = csv.writer(buf)

    # --- Session Settings Section ---
    session_cfg = match_manager.get_session(session_id)
    writer.writerow(["=== SESSION SETTINGS ==="])
    if session_cfg:
        writer.writerow(["Session ID", session_cfg.session_id])
        writer.writerow(["Session Name", getattr(session_cfg, 'name', '')])
        writer.writerow(["Session Mode", session_cfg.session_mode])
        writer.writerow(["Bot Enabled", session_cfg.bot_enabled])
        writer.writerow(["Group Size", session_cfg.group_size])
        writer.writerow(["Survey Open (days)", getattr(session_cfg, "survey_open_days", "")])
        writer.writerow(["Group Chat Duration (min)", getattr(session_cfg, "group_chat_duration_minutes", "")])
        writer.writerow(["History Limit", getattr(session_cfg, 'history_limit', '')])
        writer.writerow(["Participant Names", ", ".join(getattr(session_cfg, 'participant_names', []) or [])])
        writer.writerow([])
        writer.writerow(["=== BOT CONFIGURATION ==="])
        writer.writerow(["Bot Name", "Prompt", "Mode", "Delay (s)", "Max Tokens", "Temperature",
                         "Typing CPS", "Context Messages", "Idle Threshold", "Avatar Type"])
        for bot in (session_cfg.bots or []):
            writer.writerow([
                bot.get("name", ""),
                bot.get("prompt", ""),
                bot.get("mode", 1),
                bot.get("delay_seconds", 2),
                bot.get("max_tokens", 200),
                bot.get("temperature", 0.7),
                bot.get("typing_cps", 12),
                bot.get("context_messages", 20),
                bot.get("idle_threshold", 20),
                bot.get("avatar_type", "bot"),
            ])
    else:
        writer.writerow(["Session not found", session_id])
    writer.writerow([])

    # --- Activity Log Section ---
    writer.writerow(["=== ACTIVITY LOG ==="])
    writer.writerow(["timestamp", "event_type", "session_id", "room_id", "actor", "details"])
    activities = activity_logger.get_session_activities(session_id)
    for a in activities:
        writer.writerow([
            a.get("timestamp", ""),
            a.get("event_type", ""),
            a.get("session_id", ""),
            a.get("room_id", ""),
            a.get("actor", ""),
            json.dumps(a.get("details", {}))
        ])

    output = BytesIO(buf.getvalue().encode("utf-8"))
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=activity_{session_id}.csv"}
    )

@app.get("/api/export/room/{room_id}/messages")
async def export_room_messages(room_id: str):
    """Export full message history for a room as CSV download."""
    import csv
    from io import StringIO, BytesIO
    messages = await get_room_history(room_id, limit=10000)
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "room_id", "sender", "message"])
    for m in messages:
        writer.writerow([
            m.get("timestamp", ""),
            room_id,
            m.get("sender", ""),
            m.get("text", "")
        ])
    output = BytesIO(buf.getvalue().encode("utf-8"))
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=messages_{room_id}.csv"}
    )


# ============ Matching API (wait.html) ============

@app.get("/api/match")
async def match_user(
    session_id: str = Query(...),
    uid: str = Query(...),
    condition: Optional[str] = Query(None),
):
    """Adds a user to session queue (FIFO or stratified by condition) and returns match status."""
    if uid in match_manager.user_locations:
        loc = match_manager.user_locations[uid]
        if loc.get("session_id") == session_id:
            return {
                "status": "matched",
                "session_id": session_id,
                "group_id": loc["group_id"],
            }
    session = match_manager.get_session(session_id)
    if session and not match_manager.is_session_open(session):
        return {
            "status": "session_closed",
            "message": "This study session is no longer accepting participants.",
            "session_id": session_id,
        }
    group_id = match_manager.add_to_queue(session_id, uid, condition=condition)
    if group_id:
        asyncio.create_task(
            maybe_trigger_ai_opening(session_id, group_id, broadcast, _ai_opening_wrapper)
        )
        return {"status": "matched", "session_id": session_id, "group_id": group_id}
    session = match_manager.get_session(session_id)
    mode = session.assignment_mode if session else "fifo"
    return {"status": "waiting", "assignment_mode": mode, "condition": condition or "_default"}


@app.get("/api/embed/status")
async def embed_participant_status(
    session_id: str = Query(...),
    participant_id: str = Query(...),
):
    """Qualtrics-friendly status: waiting, matched, or in_group."""
    if participant_id in match_manager.user_locations:
        loc = match_manager.user_locations[participant_id]
        if loc.get("session_id") == session_id:
            return {
                "status": "matched",
                "session_id": session_id,
                "group_id": loc["group_id"],
                "participant_id": participant_id,
            }
    if session_id in match_manager.queues and participant_id in match_manager.queues[session_id]:
        return {"status": "waiting", "session_id": session_id, "participant_id": participant_id}
    return {"status": "not_joined", "session_id": session_id, "participant_id": participant_id}

@app.get("/api/leave")
async def leave_queue(session_id: str = Query(...), uid: str = Query(...)):
    """Removes a user from the waiting queue."""
    match_manager.remove_from_queue(session_id, uid)
    return {"status": "ok"}


# ============ Core Chat Logic & AI Processing ============

async def batch_save_messages(_msg_type: str, messages: list):
    """Persist callback for cache_manager: batch-saves cached messages to DB."""
    for msg in messages:
        await save_message(msg["room_id"], msg["sender"], msg["text"])

async def process_ai_logic(session_id: str, group_id: str, display_name: str, data: str):
    """Background processing: Caching, DB, and AI generation."""
    try:
        session_cfg = match_manager.get_session(session_id)
        if not session_cfg:
            print(f"[AI] ❌ No session config for {session_id}")
            return

        print(f"[AI] 📨 process_ai_logic: session={session_id} group={group_id} user={display_name} msg={data[:60]!r}")
        print(f"[AI]    bot_enabled={session_cfg.bot_enabled} bots={[b['name'] for b in session_cfg.bots]} mode={session_cfg.session_mode}")

        # Check if room is paused
        group_info = match_manager.get_group_info(session_id, group_id) or {}

        if group_info.get("paused", False):
            print(f"[AI] ⏸ Room {group_id} is paused, skipping AI")
            return

        # 1. Cache message
        should_flush = cache_manager.cache_message(group_id, display_name, data)

        # 2. Save to DB
        await save_message(group_id, display_name, data)

        # 3. Add to Context Manager
        ctx = get_or_create_context(group_id)
        ctx.add_message(display_name, data)

        # 4. Log activity
        activity_logger.log_user_message(session_id, group_id, display_name, data)

        # 5. Reset idle timer
        reset_idle_timer(session_id, group_id, DEFAULT_IDLE_THRESHOLD)

        # 6. Flush cache if threshold met
        if should_flush:
            await cache_manager.flush_messages(group_id)

        # 7. Bot orchestration
        if session_cfg.bot_enabled and session_cfg.bots:
            print(f"[AI] 🤖 Triggering {len(session_cfg.bots)} bots in mode {session_cfg.session_mode}")
            if session_cfg.session_mode == 1:
                # Mode 1: all bots respond independently to the latest chat state
                for bot_cfg in session_cfg.bots:
                    print(f"[AI]    → Queueing bot: {bot_cfg['name']}")
                    bot_instance = get_or_create_bot_from_cfg(group_id, bot_cfg, group_info)
                    n_ctx = bot_cfg.get('context_messages', 20)
                    full_summary = ctx.get_context_summary(num_messages=n_ctx)

                    async def make_handler(s_id, b_inst, b_cfg, n, summary, gi):
                        async def handler(resp):
                            fresh_ctx = get_context(resp.room_id)
                            latest_summary = fresh_ctx.get_context_summary(num_messages=n) if fresh_ctx else summary
                            await handle_bot_reply(s_id, resp.room_id, resp.user_id, resp.user_text, b_inst, latest_summary, b_cfg, gi)
                        return handler

                    bot_response = BotResponse(
                        room_id=group_id,
                        bot_name=bot_cfg['name'],
                        user_id=display_name,
                        user_text=data,
                        priority=1,
                        handler=await make_handler(session_id, bot_instance, bot_cfg, n_ctx, full_summary, group_info)
                    )
                    await bot_response_queue.enqueue(bot_response)
                    activity_logger.log_bot_triggered(session_id, group_id, bot_cfg['name'])

                await bot_response_queue.ensure_queue_processor(group_id)

            elif session_cfg.session_mode == 2:
                # Mode 2: Smart single bot — analyze_intent picks the most relevant bot
                history_text = ctx.get_context_summary(num_messages=5)
                chosen_name = await analyze_intent(data, session_cfg.bots, history_text)
                if not chosen_name:
                    # Fallback: pick a random bot
                    import random as _random
                    chosen_name = _random.choice(session_cfg.bots)['name']
                bot_cfg = next((b for b in session_cfg.bots if b['name'] == chosen_name), None)
                if bot_cfg:
                    bot_instance = get_or_create_bot_from_cfg(group_id, bot_cfg, group_info)
                    n_ctx = bot_cfg.get('context_messages', 20)
                    full_summary = ctx.get_context_summary(num_messages=n_ctx)

                    async def make_handler(s_id, b_inst, b_cfg, n, summary, gi):
                        async def handler(resp):
                            fresh_ctx = get_context(resp.room_id)
                            latest_summary = fresh_ctx.get_context_summary(num_messages=n) if fresh_ctx else summary
                            await handle_bot_reply(s_id, resp.room_id, resp.user_id, resp.user_text, b_inst, latest_summary, b_cfg, gi)
                        return handler

                    bot_response = BotResponse(
                        room_id=group_id,
                        bot_name=bot_cfg['name'],
                        user_id=display_name,
                        user_text=data,
                        priority=1,
                        handler=await make_handler(session_id, bot_instance, bot_cfg, n_ctx, full_summary, group_info)
                    )
                    await bot_response_queue.enqueue(bot_response)
                    activity_logger.log_bot_triggered(session_id, group_id, bot_cfg['name'])
                    await bot_response_queue.ensure_queue_processor(group_id)

            elif session_cfg.session_mode == 3:
                # Mode 3: @mention — only bots explicitly mentioned respond
                mentioned_bots = [b for b in session_cfg.bots if f"@{b['name']}" in data or b['name'].lower() in data.lower()]
                for bot_cfg in mentioned_bots:
                    bot_instance = get_or_create_bot_from_cfg(group_id, bot_cfg, group_info)
                    n_ctx = bot_cfg.get('context_messages', 20)
                    full_summary = ctx.get_context_summary(num_messages=n_ctx)

                    async def make_handler(s_id, b_inst, b_cfg, n, summary, gi):
                        async def handler(resp):
                            fresh_ctx = get_context(resp.room_id)
                            latest_summary = fresh_ctx.get_context_summary(num_messages=n) if fresh_ctx else summary
                            await handle_bot_reply(s_id, resp.room_id, resp.user_id, resp.user_text, b_inst, latest_summary, b_cfg, gi)
                        return handler

                    bot_response = BotResponse(
                        room_id=group_id,
                        bot_name=bot_cfg['name'],
                        user_id=display_name,
                        user_text=data,
                        priority=1,
                        handler=await make_handler(session_id, bot_instance, bot_cfg, n_ctx, full_summary, group_info)
                    )
                    await bot_response_queue.enqueue(bot_response)
                    activity_logger.log_bot_triggered(session_id, group_id, bot_cfg['name'])

                if mentioned_bots:
                    await bot_response_queue.ensure_queue_processor(group_id)

            else:
                # Fallback: all bots respond (same as mode 1)
                for bot_cfg in session_cfg.bots:
                    bot_instance = get_or_create_bot_from_cfg(group_id, bot_cfg, group_info)
                    n_ctx = bot_cfg.get('context_messages', 20)
                    full_summary = ctx.get_context_summary(num_messages=n_ctx)

                    async def make_handler(s_id, b_inst, b_cfg, n, summary, gi):
                        async def handler(resp):
                            fresh_ctx = get_context(resp.room_id)
                            latest_summary = fresh_ctx.get_context_summary(num_messages=n) if fresh_ctx else summary
                            await handle_bot_reply(s_id, resp.room_id, resp.user_id, resp.user_text, b_inst, latest_summary, b_cfg, gi)
                        return handler

                    bot_response = BotResponse(
                        room_id=group_id,
                        bot_name=bot_cfg['name'],
                        user_id=display_name,
                        user_text=data,
                        priority=1,
                        handler=await make_handler(session_id, bot_instance, bot_cfg, n_ctx, full_summary, group_info)
                    )
                    await bot_response_queue.enqueue(bot_response)
                    activity_logger.log_bot_triggered(session_id, group_id, bot_cfg['name'])

                await bot_response_queue.ensure_queue_processor(group_id)

    except Exception as e:
        error_id = error_handler.handle_exception(e, "process_ai_logic")
        activity_logger.log_error(session_id, error_id, "process_ai_logic")


async def handle_bot_reply(
    session_id: str,
    group_id: str,
    user_id: str,
    user_text: str,
    bot,
    full_summary,
    bot_cfg,
    group_info=None,
):
    """Handles persona-specific AI generation and broadcasting."""
    try:
        print(f"[BOT] 🟡 handle_bot_reply started: bot={bot.name} group={group_id}")
        async with get_group_lock(group_id):
            mode = bot_cfg.get('mode', 1)
            delay = bot_cfg.get('delay_seconds', 2)
            typing_cps = max(2, bot_cfg.get('typing_cps', 12))
            idle_threshold = bot_cfg.get('idle_threshold', DEFAULT_IDLE_THRESHOLD)

            print(f"[BOT]    mode={mode} delay={delay}s max_tokens={bot_cfg.get('max_tokens',200)} temp={bot_cfg.get('temperature',0.7)}")

            if mode == 1:
                await asyncio.sleep(delay)
            elif mode == 2:
                await asyncio.sleep(delay + random.uniform(0.5, 2.5))
            else:
                if random.random() < bot_cfg.get('skip_rate', 0.2):
                    activity_logger.log_bot_skipped(session_id, group_id, bot.name)
                    return
                natural_delay = max(0.5, min(8.0, len(user_text.split()) * 0.25 + random.uniform(0.5, 2.0)))
                await asyncio.sleep(natural_delay)

            clean_text = user_text.replace(f"@{bot.name}", "").strip()
            if not clean_text:
                clean_text = "Continue the conversation naturally based on prior context."

            session_cfg = match_manager.get_session(session_id)
            peer_names = [
                b["name"] for b in (session_cfg.bots if session_cfg else [])
                if b.get("name") and b["name"] != bot.name
            ]
            max_words = int(bot_cfg.get("max_words", 45))

            print(f"[BOT] 🔄 Calling generate_response for {bot.name}...")
            reply = await bot.generate_response(
                user_id, clean_text, full_summary,
                max_tokens=bot_cfg.get('max_tokens', 60),
                temperature=bot_cfg.get('temperature', 0.75),
                peer_names=peer_names,
                max_words=max_words,
            )
            if not reply:
                print(f"[BOT] ⚠️ {bot.name} returned empty reply")
                return

            print(f"[BOT] ✅ {bot.name} reply: {reply[:80]!r}")
            # No typing indicators - just send the message directly
            await broadcast(session_id, group_id, {"type": "message", "sender": bot.name, "text": reply})
            touch_group_activity(session_id, group_id)

            should_flush = cache_manager.cache_message(group_id, bot.name, reply)
            await save_message(group_id, bot.name, reply)

            ctx = get_context(group_id)
            if ctx:
                ctx.add_message(bot.name, reply)
                cache_manager.invalidate_summary(group_id)

            if should_flush:
                await cache_manager.flush_messages(group_id)

            activity_logger.log_bot_response(session_id, group_id, bot.name, reply, mode)
            reset_idle_timer(session_id, group_id, idle_threshold)

    except Exception as e:
        error_id = error_handler.handle_exception(e, "handle_bot_reply")
        activity_logger.log_error(session_id, error_id, "handle_bot_reply")


# ============ WebSocket Endpoint ============

@app.websocket("/ws/chat/{session_id}/{group_id}/{uid}")
async def websocket_chat(websocket: WebSocket, session_id: str, group_id: str, uid: str):
    await websocket.accept()

    # Get session config
    session = match_manager.get_session(session_id)
    if not session:
        await websocket.close()
        return

    # Initialize group if not exists
    group_info = match_manager.get_group_info(session_id, group_id)
    if not group_info:
        match_manager.create_group(session_id, group_id)
        group_info = match_manager.get_group_info(session_id, group_id)

    if "ws_connections" not in group_info:
        group_info["ws_connections"] = []
    if "connections" not in group_info:
        group_info["connections"] = []

    if "member_names" not in group_info:
        group_info["member_names"] = {}

    # Assign display name
    if uid not in group_info["member_names"]:
        assigned_names = set(group_info["member_names"].values())
        available_names = [name for name in session.participant_names if name not in assigned_names]
        if available_names:
            display_name = available_names[0]
        else:
            display_name = uid
        group_info["member_names"][uid] = display_name

    if uid not in group_info["members"]:
        group_info["members"].append(uid)

    match_manager.record_participant_group(session_id, uid, group_id)
    group_info["ws_connections"].append(websocket)
    group_info["connections"].append({"websocket": websocket, "uid": uid})
    touch_group_activity(session_id, group_id)
    display_name = group_info["member_names"][uid]

    init_turn_state(session, group_info)
    if session.turn_mode == "timed" and group_info.get("turn_initialized"):
        schedule_timed_turn(session_id, group_id, broadcast, session.turn_duration_seconds)
    await websocket.send_text(json.dumps({"type": "display_name", "name": display_name}))
    await broadcast_turn(session_id, group_id, broadcast)
    asyncio.create_task(
        maybe_trigger_ai_opening(session_id, group_id, broadcast, _ai_opening_wrapper)
    )
    print(f"📡 {uid} ({display_name}) connected to {group_id} (Session: {session_id})")

    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip():
                continue

            # Handle control messages (JSON)
            try:
                control = json.loads(data)
                if isinstance(control, dict) and control.get("type") == "get_display_name":
                    display_name = group_info["member_names"].get(uid, uid)
                    await websocket.send_text(json.dumps({"type": "display_name", "name": display_name}))
                    continue
                if isinstance(control, dict) and control.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue
            except (json.JSONDecodeError, TypeError):
                pass

            display_name = group_info["member_names"].get(uid, uid)

            if group_info.get("paused"):
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Chat is paused by the researcher.",
                }))
                continue

            if not can_human_speak(display_name, session, group_info):
                order = group_info.get("turn_order", [])
                idx = group_info.get("turn_index", 0) % max(len(order), 1)
                current = order[idx] if order else "another participant"
                await websocket.send_text(json.dumps({
                    "type": "turn_denied",
                    "message": f"Please wait — it is {current}'s turn.",
                    "current_speaker": current,
                }))
                continue

            touch_group_activity(session_id, group_id)
            other_conns = [
                e["websocket"] for e in group_info.get("connections", [])
                if e.get("websocket") is not websocket
            ]
            msg_payload = json.dumps({"type": "message", "sender": display_name, "text": data})
            await asyncio.gather(*[c.send_text(msg_payload) for c in other_conns], return_exceptions=True)

            if session.turn_mode != "none":
                await advance_turn(session_id, group_id, broadcast)

            asyncio.create_task(process_ai_logic(session_id, group_id, display_name, data))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        error_handler.handle_exception(e, "websocket_endpoint")
    finally:
        group_info["connections"] = [
            e for e in group_info.get("connections", []) if e.get("websocket") is not websocket
        ]
        conns = group_info.get("ws_connections", [])
        if websocket in conns:
            conns.remove(websocket)

        if not group_info.get("connections") and not conns:
            cancel_turn_timer(session_id, group_id)
            task_key = f"{session_id}_{group_id}"
            if task_key in group_idle_tasks:
                t = group_idle_tasks.pop(task_key)
                if not t.done():
                    t.cancel()
            if group_id in group_locks:
                del group_locks[group_id]
            remove_room_bots(group_id)

        print(f"🚪 {uid} disconnected from {group_id}")


# ============ Startup & Shutdown ============

@app.on_event("startup")
async def startup_event():
    print("🚀 Starting ACTR Application...")
    cache_manager.set_persist_callback(batch_save_messages)
    await cache_manager.start()
    asyncio.create_task(group_timeout_watcher())
    print("✅ Cache manager started with persist callback")

@app.on_event("shutdown")
async def shutdown_event():
    print("🛑 Shutting down application...")
    await cache_manager.stop()
    await cache_manager.flush_messages()
    print("✅ Cache flushed and manager stopped")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
