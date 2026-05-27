"""
Bot-to-bot chain triggers, rate limits, mentions, and self-correction helpers.
"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from human_defaults import HUMAN_LIKE_SESSION


def interaction_settings(session=None) -> Dict:
    """Read interaction knobs from session with safe defaults for older configs."""
    if session is None:
        session = type("_Defaults", (), {})()
    hs = HUMAN_LIKE_SESSION
    return {
        "bot_reply_on_any_message": bool(
            getattr(session, "bot_reply_on_any_message", hs["bot_reply_on_any_message"])
        ),
        "max_chain_depth": max(1, int(getattr(session, "max_chain_depth", hs["max_chain_depth"]))),
        "cooldown_per_bot_sec": max(
            0, int(getattr(session, "cooldown_per_bot_sec", hs["cooldown_per_bot_sec"]))
        ),
        "max_bot_msgs_per_minute_per_room": max(
            1,
            int(
                getattr(
                    session,
                    "max_bot_msgs_per_minute_per_room",
                    hs["max_bot_msgs_per_minute_per_room"],
                )
            ),
        ),
        "use_mentions": bool(getattr(session, "use_mentions", hs["use_mentions"])),
        "mention_prob": max(
            0.0, min(1.0, float(getattr(session, "mention_prob", hs["mention_prob"])))
        ),
        "self_correction_prob": max(
            0.0,
            min(1.0, float(getattr(session, "self_correction_prob", hs["self_correction_prob"]))),
        ),
    }


def bot_names(session) -> List[str]:
    if not session:
        return []
    return [b.get("name") for b in (session.bots or []) if b.get("name")]


def is_bot_sender(sender: str, session) -> bool:
    if not sender or not session:
        return False
    return sender in bot_names(session)


def all_peer_names(session, group_info=None, exclude: Optional[str] = None) -> List[str]:
    """Humans + bots in the room (for prompts and mentions)."""
    names: List[str] = []
    seen: Set[str] = set()
    if group_info:
        for n in (group_info.get("member_names") or {}).values():
            if n and n != exclude and n not in seen:
                seen.add(n)
                names.append(n)
    if session:
        for n in bot_names(session):
            if n != exclude and n not in seen:
                seen.add(n)
                names.append(n)
    return names


def _ensure_rate_state(group_info: Dict) -> Dict:
    if "bot_rate" not in group_info:
        group_info["bot_rate"] = {"times": [], "last_bot": {}}
    return group_info["bot_rate"]


def can_bot_send_now(group_info: Dict, bot_name: str, settings: Dict) -> bool:
    """Per-bot cooldown + room-wide messages-per-minute cap."""
    rate = _ensure_rate_state(group_info)
    now = datetime.now()

    cooldown = settings.get("cooldown_per_bot_sec", 0)
    if cooldown > 0:
        last = rate["last_bot"].get(bot_name)
        if last and (now - last).total_seconds() < cooldown:
            return False

    window_start = now - timedelta(seconds=60)
    rate["times"] = [t for t in rate["times"] if t > window_start]
    cap = settings.get("max_bot_msgs_per_minute_per_room", 24)
    if len(rate["times"]) >= cap:
        return False

    return True


def record_bot_send(group_info: Dict, bot_name: str) -> None:
    rate = _ensure_rate_state(group_info)
    now = datetime.now()
    rate["last_bot"][bot_name] = now
    rate["times"].append(now)


def pick_mention_target(
    latest_sender: str,
    latest_text: str,
    peers: List[str],
    settings: Dict,
) -> Optional[str]:
    if not settings.get("use_mentions"):
        return None
    if not peers:
        return None
    if random.random() > settings.get("mention_prob", 0.35):
        return None

    # Prefer @mention already in the triggering message
    for name in peers:
        if re.search(rf"@{re.escape(name)}\b", latest_text or "", re.IGNORECASE):
            return name

    # Otherwise pick someone other than self (can be human or bot)
    candidates = [p for p in peers if p.lower() != (latest_sender or "").lower()]
    if not candidates:
        candidates = list(peers)
    return random.choice(candidates)


def apply_mention_prefix(reply: str, target: Optional[str], settings: Dict) -> str:
    if not reply or not target or not settings.get("use_mentions"):
        return reply
    if re.search(rf"@{re.escape(target)}\b", reply, re.IGNORECASE):
        return reply
    # Light touch: only prefix sometimes so not every line has @
    if random.random() < 0.65:
        return reply
    return f"@{target} {reply}"


def build_mention_system_note(settings: Dict) -> str:
    if not settings.get("use_mentions"):
        return ""
    return (
        "You may address someone with @name when it feels natural. "
        "Treat every sender the same whether they are a person or another bot in the chat."
    )


async def maybe_self_correction(
    session_id: str,
    group_id: str,
    bot_name: str,
    original_reply: str,
    settings: Dict,
    broadcast_fn,
    save_message_fn,
    cache_message_fn,
    add_context_fn,
):
    """Lightweight 'edit': send a follow-up correction line after a short delay."""
    prob = settings.get("self_correction_prob", 0.12)
    if prob <= 0 or random.random() > prob:
        return

    await asyncio.sleep(random.uniform(2.0, 6.0))

    templates = [
        "*Let me rephrase that — {body}",
        "*Actually I meant: {body}",
        "*Quick fix on my last message: {body}",
    ]
    body = original_reply.strip()
    if len(body) > 120:
        body = body[:117] + "..."
    correction = random.choice(templates).format(body=body)

    await broadcast_fn(session_id, group_id, {"type": "message", "sender": bot_name, "text": correction})
    if cache_message_fn:
        cache_message_fn(group_id, bot_name, correction)
    if save_message_fn:
        await save_message_fn(group_id, bot_name, correction)
    if add_context_fn:
        add_context_fn(group_id, bot_name, correction)


def bots_for_message(session, message_text: str) -> List[Dict]:
    """Which bot personas may respond to this message (session_mode rules)."""
    bots = list(session.bots or []) if session else []
    if not bots:
        return []
    mode = int(getattr(session, "session_mode", HUMAN_LIKE_SESSION["session_mode"]) or 1)
    text = message_text or ""
    if mode == 3:
        return [
            b
            for b in bots
            if f"@{b['name']}" in text or b["name"].lower() in text.lower()
        ]
    # mode 1 and fallback: all bots; mode 2 handled separately in main
    if mode == 2:
        return []
    return bots


def filter_bots_for_trigger(
    bot_list: List[Dict],
    trigger_sender: str,
) -> List[Dict]:
    """Do not let a bot reply to its own message (reduces chain spam)."""
    if not trigger_sender:
        return bot_list
    return [b for b in bot_list if b.get("name") != trigger_sender]


def schedule_bot_chain(
    session_id: str,
    group_id: str,
    sender_name: str,
    sender_text: str,
    chain_depth: int,
    settings: Dict,
    process_ai_logic_fn,
) -> None:
    """After any message (human or bot), optionally trigger another bot wave."""
    if not settings.get("bot_reply_on_any_message"):
        return
    max_depth = settings.get("max_chain_depth", 3)
    if chain_depth >= max_depth:
        return

    asyncio.create_task(
        process_ai_logic_fn(
            session_id,
            group_id,
            sender_name,
            sender_text,
            chain_depth=chain_depth + 1,
            trigger_kind="bot",
        )
    )
