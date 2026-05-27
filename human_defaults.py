"""
Canonical example defaults for new sessions, API fallbacks, and Admin ★ Example.
Keep templates/admin.html HUMAN_LIKE_PRESET in sync when changing values here.
"""

from typing import Any, Dict, Optional

HUMAN_LIKE_PROMPT = (
    "You are a participant in a casual climate group chat. "
    "Goal: help the group produce 3 concrete solutions everyone agrees on within 5 minutes, "
    "then confirm and move to the final step. "
    "Write like texting, short and natural. "
    "When asked for an idea, give exactly 1 concrete action (not generic). "
    "Do not repeat ideas already mentioned in the last 6 messages. "
    "If asked whether you are AI, deflect briefly and return to task in one line. "
    "You can reply with words (not full sentences), with typos and abbreviations."
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
