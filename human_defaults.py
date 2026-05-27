"""
Canonical example defaults for new sessions, API fallbacks, and Admin ★ Example.
Keep templates/admin.html HUMAN_LIKE_PRESET in sync when changing values here.
"""

from typing import Any, Dict, Optional, Tuple

# Strongest GPT chat models in Admin (keep templates/admin.html GPT_CHAT_MODELS in sync)
GPT_CHAT_MODELS: Tuple[str, ...] = ("gpt-5.5", "gpt-5", "gpt-4o")
DEFAULT_GPT_CHAT_MODEL = "gpt-5"


def normalize_gpt_chat_model(model: Optional[str]) -> str:
    """Return a whitelisted GPT model id; unknown values fall back to default."""
    m = (model or "").strip()
    if m in GPT_CHAT_MODELS:
        return m
    return DEFAULT_GPT_CHAT_MODEL


HUMAN_LIKE_PROMPT = (
    "You are a participant in a casual climate group chat. "
    "Goal: help the group produce 3 concrete solutions everyone agrees on within 3 minutes. "
    "Treat all teammates the same; you can say hi. "
    "Jump into the discussion and deliver your first opinion quickly. "
    "When asked for an idea, give 1 concrete action (not generic) at a time. "
    "Finally the group should confirm the best three and move to the final step. "
    "Write like texting: short phrases, not full sentences; fragments, typos, and abbreviations are preferred. "
    "Use normal capitalization only—never ALL CAPS. "
    "If asked whether you are AI, deflect briefly and return to task in one short phrase. "
    "Sound lazy, minimize words, and push to finalize answers quickly. "
    "Do not say let's brainstorm—just give solutions. "
    "Do not always repeat others."
)

HUMAN_LIKE_SESSION: Dict[str, Any] = {
    "session_mode": 1,
    "bot_reply_on_any_message": True,
    "max_chain_depth": 10,
    "use_mentions": False,
    "mention_prob": 0.0,
    "self_correction_prob": 0.0,
    "ai_starts_conversation": True,
    "style_mimic_enabled": False,
    "turn_mode": "none",
}

HUMAN_LIKE_BOT: Dict[str, Any] = {
    "prompt": HUMAN_LIKE_PROMPT,
    "model": DEFAULT_GPT_CHAT_MODEL,
    "mode": 3,
    "avatar_type": "human",
    "disclosed_ai_allowed": False,
    "delay_seconds": 5,
    "typing_cps": 2,
    "temperature": 0.7,
    "context_max_chars": 100_000,
    "idle_threshold": 50,
    "skip_rate": 0.15,
    "min_words": 1,
    "max_words": 20,
    "length_variation": True,
    "emoji_enabled": False,
}


def apply_human_session_defaults(session) -> None:
    for key, value in HUMAN_LIKE_SESSION.items():
        setattr(session, key, value)


def human_like_bot_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = dict(HUMAN_LIKE_BOT)
    if overrides:
        cfg.update(overrides)
    return cfg
