from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, WebSocket, Query, Form
from pathlib import Path
import asyncio
from datetime import datetime
from match_manager import MatchManager, AdminConfig
from context_manager import get_or_create_context, remove_context, get_context, get_all_contexts
from bot_manager import get_or_create_bot, remove_bot
from dotenv import load_dotenv

load_dotenv()

# Initialize configuration and managers
admin_config = AdminConfig()
match_manager = MatchManager(admin_config.group_size)
match_manager.set_admin_config(admin_config)  # 添加这一行

# FastAPI application
app = FastAPI(title="Participant Matching System")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Template directory
TEMPLATE_DIR = Path("templates")


# ============ Home Page Routes ============

@app.get("/", response_class=HTMLResponse)
async def root():
    """Home page - User entry point."""
    html_path = TEMPLATE_DIR / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>Welcome</h1><a href='/wait?uid=user1'>Click to Start</a>"


@app.get("/wait", response_class=HTMLResponse)
async def wait_page(uid: str = Query("user1")):
    """Waiting for match page."""
    html_path = TEMPLATE_DIR / "wait.html"
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
        return content.replace("{{uid}}", uid)
    return f"<h1>Waiting for match... ({uid})</h1>"


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(uid: str = Query("user1"), room: str = Query("room1")):
    """Chat page."""
    html_path = TEMPLATE_DIR / "chat.html"
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
        content = content.replace("{{uid}}", uid)
        content = content.replace("{{room}}", room)
        return content
    return "<h1>Chat Page</h1>"


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Admin configuration page."""
    html_path = TEMPLATE_DIR / "admin.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>Admin Panel</h1>"


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Dashboard monitoring page."""
    html_path = TEMPLATE_DIR / "dashboard.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>Dashboard</h1><p>Dashboard page coming soon.</p>"


# ============ API Routes ============

@app.get("/api/admin/config")
async def get_admin_config():
    """Get current admin configuration"""
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
    """
    Update admin configuration.
    All parameters are read from request, NOT hardcoded.
    When updated, displays latest configuration in console.
    """
    # Update configuration
    admin_config.group_size = group_size
    admin_config.duration = duration
    admin_config.bot_enabled = bot_enabled
    admin_config.bot_delay = bot_delay
    admin_config.bot_name = bot_name
    admin_config.bot_prompt = bot_prompt

    # CRITICAL: Also update match_manager's group_size!
    match_manager.group_size = group_size

    # Save to file
    admin_config.save_to_file()

    # Log the update with detailed information
    print("\n" + "=" * 70)
    print("🔄 ✅ ADMIN CONFIGURATION UPDATED")
    print("=" * 70)
    print(f"📊 Current Configuration:")
    print(f"   ⚙️  Group size: {admin_config.group_size} users per room")
    print(f"   ⏱️  Chat duration: {admin_config.duration} minutes")
    print(f"   🤖 Bot enabled: {admin_config.bot_enabled}")
    print(f"   ⏳ Bot response delay: {admin_config.bot_delay} seconds")
    print(f"   🎤 Bot name: '{admin_config.bot_name}'")

    # Display bot prompt (truncate if too long)
    if len(admin_config.bot_prompt) > 100:
        print(f"   📝 Bot system prompt: {admin_config.bot_prompt[:100]}...")
    else:
        print(f"   📝 Bot system prompt: '{admin_config.bot_prompt}'")

    print("=" * 70)
    print(f"💾 Configuration saved to: config/admin_config.json")
    print("=" * 70 + "\n")

    # Return updated configuration
    return admin_config.to_dict()


# ============ Dashboard API Routes ============

@app.get("/api/admin/rooms")
async def get_all_rooms():
    """获取所有活动房间信息"""
    rooms_info = []
    for room_id, room_data in match_manager.active_rooms.items():
        # 获取上下文信息
        context = get_context(room_id)
        created_at = room_data.get("created_at")

        # 格式化创建时间
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat()
        else:
            created_at_str = str(created_at)

        rooms_info.append({
            "id": room_id,
            "participants": room_data.get("members", []),
            "created_at": created_at_str,
            "connections": len(room_data.get("ws_connections", [])),
            "bot_enabled": room_data.get("bot_enabled", False),
            "message_count": len(context.messages) if context else 0,
            "age_seconds": (datetime.now() - created_at).total_seconds() if isinstance(created_at, datetime) else 0
        })

    return {
        "rooms": rooms_info,
        "bot_enabled": admin_config.bot_enabled,
        "total_rooms": len(match_manager.active_rooms),
        "total_users": sum(len(room.get("members", [])) for room in match_manager.active_rooms.values()),
        "total_messages": sum(len(get_context(room_id).messages) if get_context(room_id) else 0
                              for room_id in match_manager.active_rooms.keys())
    }


@app.get("/api/admin/rooms/{room_id}/messages")
async def get_room_messages(room_id: str, limit: int = 100):
    """获取房间消息历史"""
    context = get_context(room_id)
    if not context:
        return {"messages": [], "room_id": room_id, "total": 0}

    messages = context.messages[-limit:] if len(context.messages) > limit else context.messages.copy()

    return {
        "room_id": room_id,
        "messages": messages,
        "total": len(context.messages),
        "participants": list(context.user_profiles.keys()) if hasattr(context, 'user_profiles') else []
    }


@app.post("/api/admin/rooms/{room_id}/end")
async def end_room_admin(room_id: str):
    """管理员结束房间"""
    if room_id in match_manager.active_rooms:
        # 结束房间
        match_manager.end_room(room_id)

        # 保存上下文并移除
        remove_context(room_id, save_to_file=True)

        # 移除bot
        remove_bot(room_id)

        print(f"✅ Admin ended room: {room_id}")
        return {"status": "success", "message": f"Room {room_id} ended"}

    return {"status": "error", "message": "Room not found"}


@app.get("/api/admin/stats")
async def get_admin_stats():
    """获取管理统计信息"""
    # 计算今日消息（简化版本）
    today = datetime.now().date()
    today_messages = 0

    # 计算活跃用户（最近5分钟有活动的）
    active_now = 0
    all_contexts = get_all_contexts()
    for context in all_contexts.values():
        if hasattr(context, 'last_activity'):
            if (datetime.now() - context.last_activity).total_seconds() < 300:  # 5分钟
                active_now += len(context.user_profiles) if hasattr(context, 'user_profiles') else 0

    # 计算消息分布
    distribution = {}
    for context in all_contexts.values():
        if hasattr(context, 'user_profiles'):
            for user, profile in context.user_profiles.items():
                distribution[user] = distribution.get(user, 0) + profile.get("message_count", 0)

    # 找出最多消息的用户
    if distribution:
        top_user = max(distribution.items(), key=lambda x: x[1])
        top_user_name, top_user_messages = top_user
    else:
        top_user_name = "None"
        top_user_messages = 0

    return {
        "today_messages": today_messages,
        "active_now": active_now,
        "avg_session": admin_config.duration,  # 使用配置的会话时长
        "top_user": top_user_name,
        "top_user_messages": top_user_messages,
        "distribution": distribution,
        "total_messages": sum(distribution.values()) if distribution else 0,
        "total_users": len(distribution),
        "active_rooms": len(match_manager.active_rooms)
    }


@app.post("/api/admin/bots/reset")
async def reset_all_bots():
    """重置所有bot实例"""
    from bot_manager import clear_all_bots
    clear_all_bots()
    print("✅ All bot instances reset by admin")
    return {"status": "success", "message": "All bots reset"}


@app.post("/api/admin/rooms/cleanup")
async def cleanup_inactive_rooms():
    """清理不活跃的房间"""
    from context_manager import cleanup_inactive_contexts

    cleaned_rooms = 0
    rooms_to_remove = []

    # 找出不活跃的房间（超过1小时）
    for room_id, room_data in match_manager.active_rooms.items():
        created_at = room_data.get("created_at")
        if isinstance(created_at, datetime):
            age_hours = (datetime.now() - created_at).total_seconds() / 3600
            if age_hours > 1:  # 超过1小时
                rooms_to_remove.append(room_id)

    # 清理房间
    for room_id in rooms_to_remove:
        match_manager.end_room(room_id)
        remove_context(room_id, save_to_file=True)
        remove_bot(room_id)
        cleaned_rooms += 1

    # 清理不活跃的上下文
    cleaned_contexts = cleanup_inactive_contexts(max_inactive_minutes=60)

    print(f"🧹 Cleaned {cleaned_rooms} inactive rooms and {cleaned_contexts} inactive contexts")

    return {
        "status": "success",
        "message": f"Cleaned {cleaned_rooms} inactive rooms and {cleaned_contexts} inactive contexts",
        "cleaned_rooms": cleaned_rooms,
        "cleaned_contexts": cleaned_contexts
    }


# ============ Match API ============

@app.get("/match")
async def match(uid: str = Query("user1")):
    """
    Check match status and join queue if not matched.
    Returns: {status: "waiting"} or {status: "matched", room_id: "...", partner_id: "..."}
    """
    # Check if user already has a room
    if uid in match_manager.user_to_room:
        room_id = match_manager.user_to_room[uid]
        room_info = match_manager.get_room_info(room_id)
        if room_info:
            members = room_info.get("members", [])
            partner_id = next((m for m in members if m != uid), None)
            return {
                "status": "matched",
                "room_id": room_id,
                "partner_id": partner_id
            }

    # Try to join queue
    partner_id = match_manager.join_queue(uid)

    if partner_id:
        # Matched successfully
        room_id = match_manager.user_to_room.get(uid)
        return {
            "status": "matched",
            "room_id": room_id,
            "partner_id": partner_id
        }
    else:
        # Still waiting
        return {"status": "waiting"}


# ============ WebSocket Chat ============

@app.websocket("/ws/chat/{room_id}/{uid}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, uid: str):
    """
    WebSocket endpoint for real-time chat.
    All delays and parameters are read from admin_config dynamically
    """
    await websocket.accept()

    # Add connection to room
    if room_id in match_manager.active_rooms:
        match_manager.active_rooms[room_id]["ws_connections"].append(websocket)

    # Get or create bot for this room ONLY if bot is enabled
    bot = None
    if admin_config.bot_enabled:
        # 只有当 bot_enabled 为 True 时才创建 bot
        bot = get_or_create_bot(room_id, admin_config.bot_prompt)
        print(f"🤖 Bot initialized for room {room_id}")
    else:
        print(f"🤖 Bot is disabled for room {room_id}")

    print(f"✅ User {uid} connected to room {room_id}")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            # Format message
            formatted_message = f"{uid}: {data}"

            # Save to context
            context = get_or_create_context(room_id)
            context.add_message(uid, data)

            # Broadcast to all connections in room
            if room_id in match_manager.active_rooms:
                connections = match_manager.active_rooms[room_id]["ws_connections"]
                for conn in connections:
                    try:
                        await conn.send_text(formatted_message)
                    except Exception as e:
                        print(f"Failed to send message: {e}")

            # Trigger bot reply ONLY if bot is enabled and bot exists
            if admin_config.bot_enabled and bot:
                asyncio.create_task(
                    bot_reply_task(room_id, uid, data, bot)
                )

    except Exception as e:
        print(f"WebSocket error: {e}")

    finally:
        # Remove connection from room
        if room_id in match_manager.active_rooms:
            if websocket in match_manager.active_rooms[room_id]["ws_connections"]:
                match_manager.active_rooms[room_id]["ws_connections"].remove(websocket)

        print(f"❌ User {uid} disconnected from room {room_id}")


async def bot_reply_task(room_id: str, user_id: str, user_message: str, bot):
    """
    Generate bot reply asynchronously.
    Uses admin_config.bot_delay from configuration, NOT hardcoded value
    """
    # 双重检查：确保 bot_enabled 仍然为 True
    if not admin_config.bot_enabled:
        print(f"⚠️ Bot task skipped: bot is disabled for room {room_id}")
        return

    try:
        # Wait for configured delay (read from admin config dynamically)
        await asyncio.sleep(admin_config.bot_delay)

        # 再次检查：确保 bot 仍然存在
        if not bot:
            print(f"⚠️ Bot task skipped: bot instance not found for room {room_id}")
            return

        # Generate bot response
        bot_reply = await bot.generate_response(user_id, user_message)

        if not bot_reply:
            return

        # Format bot message
        formatted_bot_message = f"{admin_config.bot_name}: {bot_reply}"

        # Broadcast bot message to room
        if room_id in match_manager.active_rooms:
            connections = match_manager.active_rooms[room_id]["ws_connections"]
            for conn in connections:
                try:
                    await conn.send_text(formatted_bot_message)
                except Exception as e:
                    print(f"Failed to send bot message: {e}")

        # Save to context
        context = get_context(room_id)
        if context:
            context.add_message(admin_config.bot_name, bot_reply)

    except Exception as e:
        print(f"Error in bot reply task: {e}")


@app.get("/api/admin/rooms/{room_id}/export")
async def export_room_chat_history(room_id: str, format: str = "csv"):
    """导出房间聊天历史"""
    context = get_context(room_id)
    if not context:
        return {"status": "error", "message": "Room not found or no messages"}

    # 获取房间信息
    room_info = match_manager.get_room_info(room_id)
    participants = room_info.get("members", []) if room_info else []

    if format.lower() == "csv":
        # 生成CSV内容
        csv_lines = []

        # 头部信息
        csv_lines.append(f"Room ID,{room_id}")
        csv_lines.append(f"Participants,{'; '.join(participants)}")
        csv_lines.append(f"Total Messages,{len(context.messages)}")
        csv_lines.append(f"Created At,{context.created_at}")
        csv_lines.append(f"Last Activity,{context.last_activity}")
        csv_lines.append("")  # 空行

        # 列标题
        csv_lines.append("Timestamp,Sender,Message,Turn")

        # 消息内容
        for msg in context.messages:
            timestamp = msg.get('timestamp', '')
            sender = msg.get('sender', 'Unknown')
            text = msg.get('text', '').replace('"', '""')  # Escape quotes
            turn = msg.get('turn', 0)

            csv_lines.append(f'"{timestamp}","{sender}","{text}",{turn}')

        csv_content = "\n".join(csv_lines)

        return {
            "status": "success",
            "room_id": room_id,
            "format": "csv",
            "content": csv_content,
            "filename": f"chat_history_{room_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        }

    elif format.lower() == "json":
        # 生成JSON格式
        return {
            "status": "success",
            "room_id": room_id,
            "format": "json",
            "data": {
                "room_info": {
                    "room_id": room_id,
                    "participants": participants,
                    "created_at": context.created_at.isoformat() if hasattr(context.created_at, 'isoformat') else str(
                        context.created_at),
                    "last_activity": context.last_activity.isoformat() if hasattr(context.last_activity,
                                                                                  'isoformat') else str(
                        context.last_activity),
                    "total_messages": len(context.messages)
                },
                "messages": context.messages,
                "statistics": context.get_statistics() if hasattr(context, 'get_statistics') else {}
            },
            "filename": f"chat_history_{room_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        }

    else:
        return {"status": "error", "message": "Unsupported format. Use 'csv' or 'json'."}


# ============ Startup and Shutdown ============

@app.on_event("startup")
async def startup_event():
    """Startup event - load configuration."""
    print("\n" + "=" * 70)
    print("✅ SERVER STARTUP SUCCESSFUL")
    print("=" * 70)
    print(f"📊 Admin configuration loaded:")
    print(f"   ⚙️  Group size: {admin_config.group_size} users per room")
    print(f"   ⏱️  Chat duration: {admin_config.duration} minutes")
    print(f"   🤖 Bot enabled: {admin_config.bot_enabled}")
    print(f"   ⏳ Bot response delay: {admin_config.bot_delay} seconds")
    print(f"   🎤 Bot name: '{admin_config.bot_name}'")

    # 根据 bot_enabled 状态显示不同信息
    if admin_config.bot_enabled:
        if len(admin_config.bot_prompt) > 100:
            print(f"   📝 Bot system prompt: {admin_config.bot_prompt[:100]}...")
        else:
            print(f"   📝 Bot system prompt: '{admin_config.bot_prompt}'")
    else:
        print(f"   📝 Bot system: DISABLED (no bot will join rooms)")

    print("=" * 70)
    print("🌐 Visit http://localhost:8000 to start")
    print("⚙️  Visit http://localhost:8000/admin to configure")
    print("📊 Visit http://localhost:8000/dashboard to monitor")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)