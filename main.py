import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, Query, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Internal Managers (Using your existing match_manager.py)
from match_manager import match_manager, admin_config
from context_manager import get_or_create_context, get_context
from bot_manager import get_or_create_bot

# Database Functions
from db.database import create_room_in_db, save_message, get_room_history, get_all_rooms

load_dotenv()

# ============ Initialization ============
app = FastAPI(title="Hybrid AI Chat System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMPLATE_DIR = Path("templates")

# ============ Page Routes ============

@app.get("/", response_class=HTMLResponse)
async def root():
    """Lobby Dashboard"""
    active_users_count = len(match_manager.user_to_room)
    next_uid = f"user{active_users_count + 1}"
    html_path = TEMPLATE_DIR / "index.html"
    content = html_path.read_text(encoding="utf-8")
    return content.replace("{{next_uid}}", next_uid)

@app.get("/wait", response_class=HTMLResponse)
async def wait_page():
    """Automatic Matching Page"""
    return HTMLResponse(TEMPLATE_DIR.joinpath("wait.html").read_text(encoding="utf-8"))

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(uid: str = Query(...), room: str = Query(...)):
    """Chat Interface"""
    return HTMLResponse(TEMPLATE_DIR.joinpath("chat.html").read_text(encoding="utf-8"))

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return HTMLResponse(TEMPLATE_DIR.joinpath("admin.html").read_text(encoding="utf-8"))

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return HTMLResponse(TEMPLATE_DIR.joinpath("dashboard.html").read_text(encoding="utf-8"))

# ============ Automatic Matching API ============

@app.get("/match")
async def match_endpoint(uid: str = Query(...), cond: str = Query("default")):
    """Polling endpoint for wait.html"""
    
    # 1. If user is already assigned to a room, send them there immediately
    if uid in match_manager.user_to_room:
        rid = match_manager.user_to_room[uid]
        return {"status": "matched", "room_id": rid, "partner_id": "Matched"}

    # 2. Add to queue and check for match result
    matched_group = match_manager.add_to_queue(uid, cond)
    
    if matched_group:
        # Create a unique room for this matched group
        new_room_id = f"Match_{uuid.uuid4().hex[:6]}"
        
        # Initialize in memory
        match_manager.create_room(new_room_id, matched_group)
        
        # Persist to MongoDB
        await create_room_in_db(new_room_id)
        
        return {"status": "matched", "room_id": new_room_id, "partner_id": "Found"}
    
    return {"status": "waiting"}

@app.get("/leave")
async def leave_endpoint(uid: str = Query(...), cond: str = Query("default")):
    match_manager.remove_from_queue(uid, cond)
    return {"status": "left"}

@app.get("/stats")
async def stats_endpoint():
    return {
        "active_rooms": len(match_manager.active_rooms),
        "queued_users": sum(len(q) for q in match_manager.queues.values()),
        "total_sessions": len(match_manager.user_to_room)
    }
# ============ Dashboard & Monitoring API ============

@app.get("/api/admin/rooms")
async def admin_list_rooms():
    """Detailed room info for the dashboard."""
    rooms_data = []
    # 1. Total messages count (calculated from DB)
    for rid, data in match_manager.active_rooms.items():
        history = await get_room_history(rid)
        rooms_data.append({
            "id": rid,
            "participants": data.get("members", []),
            "message_count": len(history),
            "created_at": data.get("created_at", datetime.now()).isoformat(),
            "bot_enabled": admin_config.bot_enabled,
            "connections": len(data.get("ws_connections", []))
        })
    return {
        "rooms": rooms_data, 
        "bot_enabled": admin_config.bot_enabled,
        "waiting_count": sum(len(q) for q in match_manager.queues.values())
    }

@app.get("/api/admin/rooms/{room_id}/messages")
async def admin_room_messages(room_id: str):
    """Fetch raw messages for the monitor."""
    messages = await get_room_history(room_id)
    return {"messages": messages}

@app.get("/api/admin/stats")
async def admin_detailed_stats():
    """Aggregated stats for the Dashboard 'Statistics' tab."""
    # Simplified stats - you can expand this by querying your DB
    return {
        "today_messages": 0, # Integrate with MongoDB count if needed
        "active_now": len(match_manager.user_to_room),
        "avg_session": admin_config.duration,
        "total_messages": 0
    }
# ============ Lobby & Room API ============

@app.get("/api/rooms")
async def api_list_rooms():
    """List all rooms from DB for the Lobby selection."""
    db_rooms = await get_all_rooms()
    rooms_info = []
    for room in db_rooms:
        rid = room.get("room_id")
        # Ensure rooms in DB are tracked in memory for WebSockets
        if rid not in match_manager.active_rooms:
            match_manager.create_room(rid)
        
        rooms_info.append({
            "room_id": rid,
            "user_count": len(match_manager.active_rooms[rid].get("members", []))
        })
    return {"rooms": rooms_info}

@app.post("/api/rooms/create")
async def api_create_room(room_id: str = Form(...)):
    await create_room_in_db(room_id)
    match_manager.create_room(room_id)
    return {"status": "success", "room_id": room_id}

@app.post("/api/rooms/delete/{room_id}")
async def api_delete_room(room_id: str):
    match_manager.end_room(room_id)
    return {"status": "success"}

@app.get("/api/rooms/{room_id}/history")
async def api_room_history(room_id: str):
    messages = await get_room_history(room_id)
    return {"messages": messages}

# ============ Admin API ============

@app.get("/api/admin/config")
async def get_config():
    return admin_config.to_dict()

@app.post("/api/admin/config")
async def set_config(
    group_size: int = Form(...),
    duration: int = Form(...),
    bot_enabled: bool = Form(False),
    bot_delay: int = Form(...),
    bot_name: str = Form(...),
    bot_prompt: str = Form("")
):
    admin_config.group_size = group_size
    admin_config.duration = duration
    admin_config.bot_enabled = bot_enabled
    admin_config.bot_delay = bot_delay
    admin_config.bot_name = bot_name
    admin_config.bot_prompt = bot_prompt
    
    match_manager.group_size = group_size
    admin_config.save_to_file()
    return admin_config.to_dict()

# ============ WebSocket Logic ============



@app.websocket("/ws/chat/{room_id}/{uid}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, uid: str):
    await websocket.accept()
    
    # Register room in memory if not already there
    if room_id not in match_manager.active_rooms:
        match_manager.create_room(room_id)
    
    # Add user to memory registry
    if uid not in match_manager.active_rooms[room_id]["members"]:
        match_manager.active_rooms[room_id]["members"].append(uid)
    
    match_manager.active_rooms[room_id]["ws_connections"].append(websocket)
    match_manager.user_to_room[uid] = room_id

    # Bot Setup
    bot = None
    if admin_config.bot_enabled:
        bot = get_or_create_bot(room_id, admin_config.bot_prompt)

    try:
        while True:
            data = await websocket.receive_text()
            if not data.strip(): continue

            # A. Save and Broadcast
            await save_message(room_id, uid, data)
            
            # B. Maintain local bot context
            ctx = get_or_create_context(room_id)
            ctx.add_message(uid, data)

            # C. Broadcast to all users in the room
            msg = f"{uid}: {data}"
            conns = match_manager.active_rooms[room_id]["ws_connections"]
            await asyncio.gather(*[c.send_text(msg) for c in conns], return_exceptions=True)

            # D. AI Response
            if admin_config.bot_enabled and bot:
                asyncio.create_task(handle_bot_reply(room_id, uid, data, bot))

    except Exception:
        pass
    finally:
        # Cleanup
        if room_id in match_manager.active_rooms:
            if websocket in match_manager.active_rooms[room_id]["ws_connections"]:
                match_manager.active_rooms[room_id]["ws_connections"].remove(websocket)

async def handle_bot_reply(room_id, user_id, user_text, bot):
    await asyncio.sleep(admin_config.bot_delay)
    reply = await bot.generate_response(user_id, user_text)
    
    if reply:
        bot_msg = f"{admin_config.bot_name}: {reply}"
        await save_message(room_id, admin_config.bot_name, reply)
        
        # Add to local context
        ctx = get_context(room_id)
        if ctx: ctx.add_message(admin_config.bot_name, reply)

        if room_id in match_manager.active_rooms:
            for c in match_manager.active_rooms[room_id]["ws_connections"]:
                try: await c.send_text(bot_msg)
                except: pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)