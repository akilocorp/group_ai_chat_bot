import asyncio
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, Query, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Internal Managers
from match_manager import MatchManager, AdminConfig
from context_manager import get_or_create_context, remove_context, get_context, get_all_contexts
from bot_manager import get_or_create_bot, remove_bot

# Database Functions (MongoDB)
from db.database import create_room_in_db, save_message, get_room_history, get_all_rooms

# Load environment variables (MONGO_URL, etc.)
load_dotenv()

# ============ Initialization ============

admin_config = AdminConfig()
# MatchManager handles the live WebSocket registry in memory
match_manager = MatchManager(admin_config.group_size)
match_manager.set_admin_config(admin_config)

app = FastAPI(title="AI Chat Lobby System")

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
    """Home page - Entry point for the Room Lobby."""
    active_users_count = len(match_manager.user_to_room)
    next_uid = f"user{active_users_count + 1}"
    
    html_path = TEMPLATE_DIR / "index.html"
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
        return content.replace("{{next_uid}}", next_uid)
    
    return f"<h1>Lobby Error</h1><p>index.html not found in {TEMPLATE_DIR}</p>"

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(uid: str = Query(...), room: str = Query(...)):
    """The Chat Interface."""
    html_path = TEMPLATE_DIR / "chat.html"
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
        return content.replace("{{uid}}", uid).replace("{{room}}", room)
    return "<h1>Chat Template Missing</h1>"

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Admin configuration panel."""
    html_path = TEMPLATE_DIR / "admin.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return "<h1>Admin Panel Missing</h1>"

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """System monitoring dashboard."""
    html_path = TEMPLATE_DIR / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return "<h1>Dashboard Missing</h1>"

# ============ Lobby & Room API ============

@app.get("/api/rooms")
async def list_rooms():
    """Syncs MongoDB rooms with memory and returns them for the lobby list."""
    db_rooms = await get_all_rooms()
    
    # If no rooms exist in DB, create a default one
    if not db_rooms:
        await create_room_in_db("Lobby_1")
        db_rooms = [{"room_id": "Lobby_1"}]

    rooms_info = []
    for room in db_rooms:
        rid = room.get("room_id")
        # Ensure MongoDB rooms are registered in MatchManager memory for WebSockets
        if rid not in match_manager.active_rooms:
            match_manager.create_room(rid)
            
        rooms_info.append({
            "room_id": rid,
            "user_count": len(match_manager.active_rooms[rid].get("members", []))
        })
    return {"rooms": rooms_info}

@app.post("/api/rooms/create")
async def create_new_room(room_id: str = Form(...)):
    """API to create a new persistent room."""
    await create_room_in_db(room_id)
    if room_id not in match_manager.active_rooms:
        match_manager.create_room(room_id)
    return {"status": "success", "room_id": room_id}

@app.get("/api/rooms/{room_id}/history")
async def room_history(room_id: str):
    """Fetches message history for a specific room from MongoDB."""
    messages = await get_room_history(room_id)
    return {"messages": messages}

# ============ Admin API ============

@app.get("/api/admin/config")
async def get_admin_config():
    return admin_config.to_dict()

@app.post("/api/admin/config")
async def set_admin_config(
    group_size: int = Form(...),
    duration: int = Form(...),
    bot_enabled: bool = Form(...),
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
    print(f"⚙️ Admin Config Updated: Bot={bot_enabled}, Name={bot_name}")
    return admin_config.to_dict()

# ============ WebSocket Chat Engine ============



@app.websocket("/ws/chat/{room_id}/{uid}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, uid: str):
    await websocket.accept()
    
    # 1. Room setup
    if room_id not in match_manager.active_rooms:
        match_manager.create_room(room_id)
    
    # Add member and connection to tracking
    if uid not in match_manager.active_rooms[room_id]["members"]:
        match_manager.active_rooms[room_id]["members"].append(uid)
        
    match_manager.active_rooms[room_id]["ws_connections"].append(websocket)
    match_manager.user_to_room[uid] = room_id

    # 2. Bot Initialization
    bot = None
    if admin_config.bot_enabled:
        bot = get_or_create_bot(room_id, admin_config.bot_prompt)

    print(f"✅ {uid} joined {room_id}")

    try:
        while True:
            # Wait for user message
            data = await websocket.receive_text()
            if not data.strip():
                continue

            # A. Save to MongoDB (Persistent)
            await save_message(room_id, uid, data)

            # B. Add to local Context (For current Bot memory)
            context = get_or_create_context(room_id)
            context.add_message(uid, data)

            # C. Broadcast to all users in the room
            formatted_msg = f"{uid}: {data}"
            connections = match_manager.active_rooms[room_id]["ws_connections"]
            
            await asyncio.gather(
                *[conn.send_text(formatted_msg) for conn in connections],
                return_exceptions=True
            )

            # D. Trigger AI Response
            if admin_config.bot_enabled and bot:
                asyncio.create_task(bot_reply_task(room_id, uid, data, bot))

    except Exception as e:
        print(f"⚠️ WS Error for {uid}: {e}")
    finally:
        # Cleanup on disconnect
        if room_id in match_manager.active_rooms:
            if websocket in match_manager.active_rooms[room_id]["ws_connections"]:
                match_manager.active_rooms[room_id]["ws_connections"].remove(websocket)
        print(f"❌ {uid} left {room_id}")

async def bot_reply_task(room_id: str, user_id: str, user_message: str, bot):
    """Handles delayed AI response and persistence."""
    if not admin_config.bot_enabled:
        return

    await asyncio.sleep(admin_config.bot_delay)
    
    bot_reply = await bot.generate_response(user_id, user_message)
    if bot_reply:
        formatted_bot_msg = f"{admin_config.bot_name}: {bot_reply}"
        
        # Broadcast bot message
        if room_id in match_manager.active_rooms:
            connections = match_manager.active_rooms[room_id]["ws_connections"]
            for conn in connections:
                try:
                    await conn.send_text(formatted_bot_msg)
                except:
                    pass
        
        # Save Bot message to MongoDB
        await save_message(room_id, admin_config.bot_name, bot_reply)
        
        # Add to local context
        ctx = get_context(room_id)
        if ctx:
            ctx.add_message(admin_config.bot_name, bot_reply)

# ============ Lifecycle ============

@app.on_event("startup")
async def startup_event():
    print("\n" + "=" * 50)
    print("🚀 SERVER STARTING - LOBBY SYSTEM ACTIVE")
    print(f"📡 MongoDB Check: {os.getenv('MONGO_URL')[:15]}...")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)