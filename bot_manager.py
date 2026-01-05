import asyncio
from typing import Optional, Dict
from dotenv import load_dotenv
import os

load_dotenv()

from openai import AsyncOpenAI

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Default system prompt when no prompt is provided
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, neutral conversational partner. "
    "Use clear and respectful language, ask clarifying questions when needed, "
    "and keep the conversation natural and balanced."
)


class ChatBot:
    """
    Chat Bot Class - Unified behavior without personalities.
    Uses a single system prompt provided at initialization.
    Updated to support OpenAI 2.x API.
    """

    def __init__(self, room_id: str, system_prompt: str):
        """
        Initialize the bot.

        Parameters:
        - room_id: Room ID for the bot instance
        - system_prompt: System prompt that defines the bot's behavior and instructions
                         If empty or None, uses DEFAULT_SYSTEM_PROMPT
        """
        self.room_id = room_id

        # Handle empty or None prompt
        if not system_prompt or system_prompt.strip() == "":
            self.system_prompt = DEFAULT_SYSTEM_PROMPT
            print(f"⚠️ Bot Room {room_id} initialized with DEFAULT system prompt")
        else:
            self.system_prompt = system_prompt
            print(f"✅ Bot Room {room_id} initialized with custom system prompt")

        self.conversation_history = []

    async def generate_response(self, user_id: str, user_message: str) -> Optional[str]:
        """
        Generate bot response.

        Parameters:
        - user_id: User ID
        - user_message: User message

        Returns:
        Bot response or None if generation fails
        """
        try:
            # Add user message to conversation history
            self.conversation_history.append(
                {"role": "user", "content": f"{user_id}: {user_message}"}
            )

            # Build message list with system prompt
            messages = [
                {"role": "system", "content": self.system_prompt}
            ]

            # Add recent conversation history (keep last 10 messages)
            recent_history = self.conversation_history[-10:]
            messages.extend(recent_history)

            # Call OpenAI API
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                max_tokens=150,
                temperature=0.7,
                top_p=0.9
            )

            # Extract reply
            reply = response.choices[0].message.content.strip()

            # Add bot response to history
            self.conversation_history.append(
                {"role": "assistant", "content": reply}
            )

            print(f"🤖 Room {self.room_id} Generated reply: {reply[:50]}...")
            return reply

        except Exception as e:
            print(f"❌ Failed to generate bot response: {e}")
            # Return fallback reply when API call fails
            fallback_replies = [
                "That sounds interesting! Could you tell me more?",
                "I see. Can you elaborate on that?",
                "That's a good point. What else would you like to discuss?",
                "Thanks for sharing! Do you have any other thoughts?",
            ]
            import random
            return random.choice(fallback_replies)

    def update_system_prompt(self, new_prompt: str):
        """
        Update the system prompt for this bot instance.

        Parameters:
        - new_prompt: New system prompt text
        """
        # Handle empty prompt
        if not new_prompt or new_prompt.strip() == "":
            new_prompt = DEFAULT_SYSTEM_PROMPT
            print(f"⚠️ Bot Room {self.room_id} system prompt updated to DEFAULT")
        else:
            print(f"✅ Bot Room {self.room_id} system prompt updated")

        self.system_prompt = new_prompt

    def get_conversation_summary(self) -> Dict:
        """
        Get conversation summary.

        Returns:
        Dictionary with conversation metadata
        """
        return {
            "room_id": self.room_id,
            "system_prompt": self.system_prompt[:100] + "..." if len(self.system_prompt) > 100 else self.system_prompt,
            "message_count": len(self.conversation_history),
            "conversation": self.conversation_history[-5:] if self.conversation_history else []  # Last 5 messages only
        }

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []
        print(f"🗑️ Bot Room {self.room_id} conversation history cleared")


# Global bot instances storage
bot_instances: Dict[str, ChatBot] = {}


def get_or_create_bot(room_id: str, system_prompt: str) -> ChatBot:
    """
    Get or create bot instance for a room.

    KEY CHANGE: If bot already exists, UPDATE its system_prompt to the latest!
    This ensures that when admin changes the prompt, existing bots get updated.

    Parameters:
    - room_id: Room ID
    - system_prompt: System prompt for the bot (use admin config's bot_prompt)

    Returns:
    ChatBot instance
    """
    # Handle empty prompt
    if not system_prompt or system_prompt.strip() == "":
        system_prompt = DEFAULT_SYSTEM_PROMPT
        prompt_source = "default"
    else:
        prompt_source = "custom"

    if room_id not in bot_instances:
        # Create new bot
        bot_instances[room_id] = ChatBot(room_id, system_prompt)
        print(f"✅ Created new bot for room {room_id} ({prompt_source} prompt)")
    else:
        # Bot already exists, UPDATE its system prompt to latest config
        existing_bot = bot_instances[room_id]
        if existing_bot.system_prompt != system_prompt:
            existing_bot.update_system_prompt(system_prompt)
            print(f"🔄 Updated existing bot prompt for room {room_id}")

    return bot_instances[room_id]


def get_bot(room_id: str) -> Optional[ChatBot]:
    """
    Get bot instance if it exists.

    Parameters:
    - room_id: Room ID

    Returns:
    ChatBot instance or None if not found
    """
    return bot_instances.get(room_id)


def remove_bot(room_id: str):
    """
    Remove bot instance.

    Parameters:
    - room_id: Room ID to remove
    """
    if room_id in bot_instances:
        del bot_instances[room_id]
        print(f"🗑️ Bot Room {room_id} removed")


def update_bot_system_prompt(room_id: str, new_prompt: str):
    """
    Update bot system prompt for an existing bot instance.

    Parameters:
    - room_id: Room ID
    - new_prompt: New system prompt text
    """
    bot = get_bot(room_id)
    if bot:
        bot.update_system_prompt(new_prompt)
        print(f"✅ Bot prompt updated for room {room_id}")
    else:
        print(f"⚠️ Bot not found for room {room_id}")


def update_all_bots_prompt(new_prompt: str):
    """
    Force update system prompt for all existing bots.

    Parameters:
    - new_prompt: New system prompt text
    """
    updated_count = 0
    for room_id, bot in bot_instances.items():
        if bot.system_prompt != new_prompt:
            bot.update_system_prompt(new_prompt)
            updated_count += 1

    print(f"✅ Updated system prompt for {updated_count} bots")
    return updated_count


def get_all_bots() -> Dict[str, ChatBot]:
    """
    Get all bot instances.

    Returns:
    Dictionary of all bot instances
    """
    return bot_instances.copy()


def clear_all_bots():
    """Clear all bot instances."""
    bot_instances.clear()
    print("🗑️ All bots cleared")


def get_bot_count() -> int:
    """Get total number of bot instances."""
    return len(bot_instances)


# Module loading verification
if __name__ == "__main__":
    print("✅ bot_manager.py module loaded successfully")
    print(f"📊 Default system prompt: {DEFAULT_SYSTEM_PROMPT[:60]}...")

    print("\n🧪 Testing bot creation...")

    # Test 1: Bot with custom prompt
    test_prompt = "You are a friendly assistant."
    test_bot = get_or_create_bot("test_room_001", test_prompt)
    print(f"Test bot created for room: {test_bot.room_id}")
    print(f"System prompt: {test_bot.system_prompt[:60]}...")

    # Test 2: Bot with empty prompt (should use default)
    test_bot2 = get_or_create_bot("test_room_002", "")
    print(f"\nEmpty prompt test bot: {test_bot2.room_id}")
    print(f"System prompt: {test_bot2.system_prompt[:60]}...")

    print(f"\n📊 Total bots: {get_bot_count()}")