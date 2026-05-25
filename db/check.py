import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import os

# 1. Force find the .env file
# Logic updated to ensure base_dir is correctly identified regardless of execution path
current_dir = Path(__file__).resolve().parent
base_dir = current_dir.parent
env_path = base_dir / '.env'

print(f"📂 Scanning for configuration at: {env_path}")
load_dotenv(dotenv_path=env_path)

async def test_connection():
    uri = os.getenv("MONGO_URL")
    
    # Check if URI exists BEFORE trying to slice it
    if uri is None:
        print("❌ ERROR: MONGO_URL is None. The .env file was not loaded correctly.")
        print(f"💡 Action: Ensure '.env' contains 'MONGO_URL=mongodb+srv://...'")
        return

    # Security: Only show the protocol and a tiny bit of the address
    print(f"🔍 Found URI starting with: {uri[:15]}...")
    
    if "localhost" in uri or "127.0.0.1" in uri:
        print("⚠️  Warning: Using Localhost. Multi-user sensing works best with Atlas for persistence.")

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    
    try:
        print("📡 Pinging Cluster...")
        await client.admin.command('ping')
        print("✅ CONNECTION SUCCESS: Connected to MongoDB Cluster!")

        # 2. Test Write/Read Permissions (Crucial for Sensing Stats)
        print("🧪 Testing Read/Write permissions for Sensing Logic...")
        db = client.chat_db
        test_col = db.get_collection("connection_test")
        
        # Write a test record
        test_doc = {"test": True, "timestamp": "now"}
        result = await test_col.insert_one(test_doc)
        
        if result.inserted_id:
            print("📝 Write Permission: OK")
            # Cleanup test record
            await test_col.delete_one({"_id": result.inserted_id})
            print("🗑️ Cleanup: OK")
        
        # Check for our new required collections
        collections = await db.list_collection_names()
        required = ["rooms", "messages", "bot_stats"]
        for col in required:
            if col in collections:
                print(f"📦 Collection '{col}': FOUND")
            else:
                print(f"⚠️  Collection '{col}': MISSING (Will be auto-created on first bot call)")

        print("\n🏆 SYSTEM READY: Sensing logic can now persist data to the cloud.")

    except Exception as e:
        print(f"\n❌ CONNECTION FAILED: {e}")
        print("\n🔧 Troubleshooting Tips:")
        print("1. Check if your IP address is whitelisted in MongoDB Atlas.")
        print("2. Ensure the username/password in MONGO_URL are correct.")
        print("3. Check if your firewall is blocking port 27017.")

if __name__ == "__main__":
    asyncio.run(test_connection())