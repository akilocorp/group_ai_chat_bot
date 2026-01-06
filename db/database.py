from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import os
from dotenv import load_dotenv

# Load the variables from the .env file
load_dotenv()

# Update with your MongoDB URI (Local or MongoDB Atlas)
MONGO_DETAILS = os.getenv("MONGO_URL")
if not MONGO_DETAILS:
    print("❌ ERROR: MONGO_URL not found in environment variables!")

client = AsyncIOMotorClient(MONGO_DETAILS)
database = client.chat_db
rooms_collection = database.get_collection("rooms")
messages_collection = database.get_collection("messages")

# --- Database Logic ---

async def create_room_in_db(room_id: str):
    """Creates a room if it doesn't exist."""
    await rooms_collection.update_one(
        {"room_id": room_id},
        {"$setOnInsert": {"room_id": room_id, "created_at": datetime.now()}},
        upsert=True
    )

async def save_message(room_id: str, sender: str, text: str):
    """Saves a single chat message to the collection."""
    message = {
        "room_id": room_id,
        "sender": sender,
        "text": text,
        "timestamp": datetime.now()
    }
    await messages_collection.insert_one(message)

async def get_room_history(room_id: str, limit: int = 50):
    """Retrieves the last 50 messages for a specific room."""
    cursor = messages_collection.find({"room_id": room_id}).sort("timestamp", 1).limit(limit)
    messages = await cursor.to_list(length=limit)
    # Convert BSON/ObjectId to strings for JSON compatibility
    for msg in messages:
        msg["_id"] = str(msg["_id"])
    return messages

async def get_all_rooms():
    """Retrieves all available rooms and their current user counts (optional logic)."""
    cursor = rooms_collection.find()
    rooms = await cursor.to_list(length=100)
    for r in rooms:
        r["_id"] = str(r["_id"])
    return rooms