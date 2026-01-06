import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import os

# 1. Force find the .env file
# Since you are running from 'chatgroup' folder but script is in 'db' folder
current_dir = Path(__file__).resolve().parent
base_dir = current_dir.parent
env_path = base_dir / '.env'

print(f"📂 Looking for .env at: {env_path}")
load_dotenv(dotenv_path=env_path)

async def test_connection():
    uri = os.getenv("MONGO_URL")
    
    # Check if URI exists BEFORE trying to slice it
    if uri is None:
        print("❌ ERROR: MONGO_URL is None. The .env file was not loaded correctly.")
        print(f"Check if the file exists at: {env_path}")
        return

    print(f"🔍 Testing URI: {uri[:20]}... (hidden for safety)")
    
    if "localhost" in uri:
        print("⚠️ Warning: Your URI is pointing to localhost. Are you sure you saved the Atlas URL in .env?")

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    
    try:
        print("📡 Sending ping to MongoDB Atlas...")
        await client.admin.command('ping')
        print("✅ SUCCESS: You are connected to MongoDB Atlas!")
    except Exception as e:
        print(f"\n❌ CONNECTION FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())