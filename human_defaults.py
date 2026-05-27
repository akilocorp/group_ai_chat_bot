"""
Canonical example defaults for new sessions, API fallbacks, and Admin ★ Example.
Keep templates/admin.html HUMAN_LIKE_PRESET in sync when changing values here.
"""

from typing import Any, Dict, Optional

HUMAN_LIKE_PROMPT = (
    "You are a participant in a casual group chat about climate and global warming "
    "to figure out three optimal solutions. "
    "Write like texting: short fragments, slang, occasional typos. "
    "React more than interview — do not ask a question every time. "
    "Never volunteer a numbered top 3 list unless someone asks. "
    "If asked whether you are AI, deflect it."
)

HUMAN_LIKE_SESSION: Dict[str, Any] = {
    "session_mode": 1,
    "bot_reply_on_any_message": False,
    "max_chain_depth": 3,
    "cooldown_per_bot_sec": 12,
    "max_bot_msgs_per_minute_per_room": 12,
    "use_mentions": False,
    "mention_prob": 0.0,
    "self_correction_prob": 0.0,
    "ai_starts_conversation": False,
    "style_mimic_enabled": False,
    "turn_mode": "none",
}

HUMAN_LIKE_BOT: Dict[str, Any] = {
    "prompt": HUMAN_LIKE_PROMPT,
    "mode": 3,
    "avatar_type": "human",
    "disclosed_ai_allowed": False,
    "delay_seconds": 5,
    "typing_cps": 3,
    "temperature": 0.82,
    "context_max_chars": 100_000,
    "idle_threshold": 50,
    "skip_rate": 0.45,
    "min_words": 1,
    "max_words": 12,
    "length_variation": True,
}


def apply_human_session_defaults(session) -> None:
    for key, value in HUMAN_LIKE_SESSION.items():
        setattr(session, key, value)


def human_like_bot_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = dict(HUMAN_LIKE_BOT)
    if overrides:
        cfg.update(overrides)
    return cfg
