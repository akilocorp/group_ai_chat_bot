import asyncio
from typing import Optional, Dict, List
from dotenv import load_dotenv
import os
import random

from openai import AsyncOpenAI

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Default system prompt when no specific instructions are provided
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, neutral conversational partner. "
    "Use clear and respectful language, ask clarifying questions when needed, "
    "and keep the conversation natural and balanced. "
    "Never copy the user's message verbatim. Add your own reasoning or perspective based on full chat context."
)

# Fallback replies used when the AI API is unavailable
FALLBACK_REPLIES = [
    "What do you think of it?",
    "Well, I'm not sure...",
    "That's an interesting point. What does everyone else think?",
    "Hmm, I need a moment to think about that.",
    "Could you tell me more?",
    "I see what you mean. What's your take on it?",
    "That's worth considering. Anyone else have thoughts?",
    "Not sure I have a strong opinion — what about you?",
]

class ChatBot:
    """
    Chat Bot Class representing a unique persona.
    Each instance manages its own identity, prompt, and conversation history.
    """

    def __init__(self, room_id: str, name: str, system_prompt: str):
        """
        Initialize the bot with a name and room context.
        """
        self.room_id = room_id
        self.name = name
        
        # Identity injection: Ensure the bot knows its name and role
        identity_instr = f"Your name is {self.name}. Always stay in character as {self.name}. "
        
        if not system_prompt or system_prompt.strip() == "":
            self.system_prompt = identity_instr + DEFAULT_SYSTEM_PROMPT
        else:
            self.system_prompt = identity_instr + system_prompt

        self.conversation_history = []
        print(f"✅ Bot '{self.name}' initialized for room {room_id}")

    async def generate_response(self, user_id: str, user_message: str, full_context_summary: str,
                                max_tokens: int = 200, temperature: float = 0.7) -> Optional[str]:
        """
        Generates a response using the full room history provided by the ContextManager.
        max_tokens and temperature are passed per-call from bot_cfg so admin settings take effect.
        """
        try:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "system", "content": f"Here is the current chat context:\n{full_context_summary}"},
                {"role": "user", "content": f"{user_id}: {user_message}"}
            ]

            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ Generation Error: {e} — using fallback reply")
            return random.choice(FALLBACK_REPLIES)
    def update_persona(self, new_prompt: str):
        """Update the system instructions for this specific persona."""
        identity_instr = f"Your name is {self.name}. Always stay in character as {self.name}. "
        self.system_prompt = identity_instr + (new_prompt if new_prompt.strip() else DEFAULT_SYSTEM_PROMPT)

# ==========================================
# GLOBAL REGISTRY MANAGEMENT
# ==========================================

# Structure: { "room_id": { "BotName": ChatBot_Instance } }
room_bot_registry: Dict[str, Dict[str, ChatBot]] = {}
# Add this to your bot_manager.py

async def analyze_intent(user_text: str, bots_config: list, history_text: str) -> Optional[str]:
    """
    Decides which bot should speak based on the current message AND recent history.
    """
    if not bots_config: return None

    persona_list = "\n".join([f"- {b['name']}: {b['prompt']}" for b in bots_config])

    orchestrator_prompt = f"""
    You are a Chat Orchestrator for a group chat. 
    
    RECENT HISTORY:
    {history_text}

    NEW MESSAGE: "{user_text}"

    AVAILABLE PERSONAS:
    {persona_list}

    TASK:
    - If the user is clearly continuing a conversation with a specific bot, pick that bot.
    - If the user mentions a bot name, pick that bot.
    - If the topic matches a bot's prompt, pick that bot.
    - Otherwise, return "NONE".

    ONLY return the NAME or "NONE".
    """

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": orchestrator_prompt}],
            max_tokens=10, # Very small for speed
            temperature=0
        )
        decision = response.choices[0].message.content.strip().replace("@", "")
        # Robust name matching
        for bot in bots_config:
            if bot['name'].lower() in decision.lower():
                return bot['name']
        return None
    except:
        return None
def get_or_create_bot(room_id: str, bot_name: str, system_prompt: str) -> ChatBot:
    """
    Sensing Logic Helper: 
    Retrieves or creates a specific bot persona within a room.
    If the prompt has changed in Admin, it updates the existing persona.
    """
    if room_id not in room_bot_registry:
        room_bot_registry[room_id] = {}

    room_bots = room_bot_registry[room_id]

    if bot_name not in room_bots:
        # Create new persona instance
        room_bots[bot_name] = ChatBot(room_id, bot_name, system_prompt)
    else:
        # Persona exists, update instructions to ensure admin changes apply
        room_bots[bot_name].update_persona(system_prompt)

    return room_bots[bot_name]

def get_bot(room_id: str, bot_name: str) -> Optional[ChatBot]:
    """Retrieve a bot by name from a specific room."""
    return room_bot_registry.get(room_id, {}).get(bot_name)

def remove_room_bots(room_id: str):
    """Clean up all bot personas when a room is closed."""
    if room_id in room_bot_registry:
        del room_bot_registry[room_id]
        print(f"🗑️ Cleaned up all bot personas for room {room_id}")

def remove_bot_persona(room_id: str, bot_name: str):
    """Remove a specific persona from a room."""
    if room_id in room_bot_registry and bot_name in room_bot_registry[room_id]:
        del room_bot_registry[room_id][bot_name]
        print(f"🗑️ Persona '{bot_name}' removed from room {room_id}")

def clear_all_registries():
    """Clear everything (System Reset)."""
    room_bot_registry.clear()
    print("🗑️ Global Bot Registry reset.")

def get_active_bots_in_room(room_id: str) -> List[str]:
    """List all bots currently 'awake' in a room."""
    return list(room_bot_registry.get(room_id, {}).keys())

# ==========================================
# TEST AND VERIFICATION
# ==========================================

if __name__ == "__main__":
    print("✅ bot_manager.py module loaded successfully")
    
    # Simple Local Test
    async def test():
        print("\n🧪 Testing Persona Sensing...")
        b1 = get_or_create_bot("room_test", "Jarvis", "You are a polite butler.")
        b2 = get_or_create_bot("room_test", "Harley", "You are a chaotic prankster.")
        
        print(f"Room active bots: {get_active_bots_in_room('room_test')}")
        
        resp = await b1.generate_response("User1", "Help me with my schedule.")
        print(f"Jarvis Response: {resp}")
        
    # asyncio.run(test()) # Uncomment to run manual test