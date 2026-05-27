import asyncio
import re
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
    "You are a casual teammate in a small group chat. "
    "Reply in 1–2 short sentences like texting. One idea or question at a time. "
    "Never use numbered lists unless someone explicitly asked for a list."
)

HUMAN_OUTPUT_RULES = """
STRICT CHAT FORMAT (always follow):
- You are a teammate in a group chat. Stay in character; do not mention being an AI system unless asked.
- Speak ONLY as yourself ({bot_name}). Never write lines for other people.
- Never prefix your message with "{bot_name}:" or roleplay a script (no "a: ... b: ...").
- Maximum ~35 words unless the latest message clearly asks for a long answer.
- No "Hello team", no speeches, no essays, no bullet/numbered lists unless explicitly requested.
- Do not repeat or summarize what someone just said; add something new or ask one short question.
- Other participants in the room: {peers}. You are not them.
"""

# Appended only when disclosed_ai_allowed is set on the persona (same base prompt otherwise).
DISCLOSED_AI_TEAMMATE_NOTE = (
    "\n[Roster note: this teammate may use AI tools. "
    "Keep replies brief and conversational.]"
)

# Short fallbacks when the AI API is unavailable

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


def build_style_rules(bot_name: str, peer_names: Optional[List[str]] = None) -> str:
    peers = ", ".join(peer_names) if peer_names else "(other teammates)"
    return HUMAN_OUTPUT_RULES.format(bot_name=bot_name, peers=peers)


def sanitize_bot_reply(
    text: str,
    bot_name: str,
    peer_names: Optional[List[str]] = None,
    max_words: int = 45,
) -> str:
    """Strip multi-speaker scripts, lists, and runaway length."""
    if not text:
        return text

    out_lines: List[str] = []
    all_names = {bot_name.lower()}
    if peer_names:
        all_names.update(n.lower() for n in peer_names if n)

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.+)$", line)
        if m:
            speaker, content = m.group(1), m.group(2).strip()
            if speaker.lower() == bot_name.lower():
                out_lines.append(content)
            continue
        out_lines.append(line)

    cleaned = " ".join(out_lines).strip() or text.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    # Drop numbered-list essays unless very short
    if re.search(r"\b[1-5]\.\s", cleaned) and len(cleaned.split()) > max_words // 2:
        before_list = re.split(r"\s*1\.\s", cleaned, maxsplit=1)[0].strip()
        if len(before_list.split()) >= 4:
            cleaned = before_list

    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(".,;:") + "…"

    return cleaned


def _cap_sentences(text: str, max_sentences: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(parts) <= max_sentences:
        return text.strip()
    return " ".join(parts[:max_sentences]).strip()


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
        
        base = DEFAULT_SYSTEM_PROMPT if not system_prompt or not system_prompt.strip() else system_prompt
        self.system_prompt = identity_instr + base + build_style_rules(name)

        self.conversation_history = []
        print(f"✅ Bot '{self.name}' initialized for room {room_id}")

    async def generate_response(
        self,
        user_id: str,
        user_message: str,
        full_context_summary: str,
        max_tokens: int = 60,
        temperature: float = 0.75,
        peer_names: Optional[List[str]] = None,
        max_words: int = 45,
    ) -> Optional[str]:
        """
        Generates a response using the full room history provided by the ContextManager.
        max_tokens and temperature are passed per-call from bot_cfg so admin settings take effect.
        """
        try:
            cap_tokens = max(20, min(int(max_tokens), 120))
            messages = [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "system",
                    "content": (
                        f"Roommates (do not impersonate): {', '.join(peer_names) if peer_names else 'others'}\n"
                        f"Chat so far:\n{full_context_summary or '(just starting)'}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Latest message from {user_id}: {user_message}\n\n"
                        f"Reply as {self.name} only, in 1–2 short casual sentences."
                    ),
                },
            ]

            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                max_tokens=cap_tokens,
                temperature=temperature,
                frequency_penalty=0.35,
                presence_penalty=0.2,
            )

            raw = response.choices[0].message.content.strip()
            reply = sanitize_bot_reply(raw, self.name, peer_names, max_words=max_words)
            return _cap_sentences(reply, 2)
        except Exception as e:
            print(f"❌ Generation Error: {e} — using fallback reply")
            return random.choice(FALLBACK_REPLIES)
    def update_persona(self, new_prompt: str):
        """Update the system instructions for this specific persona."""
        identity_instr = f"Your name is {self.name}. Always stay in character as {self.name}. "
        base = new_prompt if new_prompt.strip() else DEFAULT_SYSTEM_PROMPT
        self.system_prompt = identity_instr + base + build_style_rules(self.name)

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
def compose_bot_prompt(system_prompt: str, disclosed_ai_allowed: bool = False) -> str:
    """Build system prompt; optional note when roster tag “may use AI” is active."""
    base = system_prompt.strip() if system_prompt and system_prompt.strip() else DEFAULT_SYSTEM_PROMPT
    if disclosed_ai_allowed:
        return base + DISCLOSED_AI_TEAMMATE_NOTE
    return base


def get_or_create_bot_from_cfg(room_id: str, bot_cfg: dict, group_info: dict = None) -> ChatBot:
    """Create/update a persona from an admin bot config dict."""
    from study_conditions import effective_bot_cfg

    cfg = effective_bot_cfg(bot_cfg, group_info)
    return get_or_create_bot(
        room_id,
        cfg.get("name", "Assistant"),
        cfg.get("prompt", ""),
        disclosed_ai_allowed=bool(cfg.get("disclosed_ai_allowed")),
    )


def get_or_create_bot(
    room_id: str,
    bot_name: str,
    system_prompt: str,
    disclosed_ai_allowed: bool = False,
) -> ChatBot:
    """
    Sensing Logic Helper: 
    Retrieves or creates a specific bot persona within a room.
    If the prompt has changed in Admin, it updates the existing persona.
    """
    if room_id not in room_bot_registry:
        room_bot_registry[room_id] = {}

    room_bots = room_bot_registry[room_id]

    full_prompt = compose_bot_prompt(system_prompt, disclosed_ai_allowed)
    if bot_name not in room_bots:
        room_bots[bot_name] = ChatBot(room_id, bot_name, full_prompt)
    else:
        room_bots[bot_name].update_persona(full_prompt)

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