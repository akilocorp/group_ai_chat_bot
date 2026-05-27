"""
Resolve optional embed `condition` parameter to per-group roster labels.

Supported values (bot display names a, b are examples — matching is by name):
  cond1_a, cond1_b  — show “may use AI” on that persona only
  cond2, control    — no roster tags
  cond1             — pick one persona at random for the tag (server-side)

Pass via embed URL: …&condition=${e://Field/condition}
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple


def _bot_names(bots: List[Dict]) -> List[str]:
    return [b["name"] for b in bots if b.get("name")]


def resolve_ai_disclosed_bot(
    bots: List[Dict],
    condition: Optional[str],
    *,
    rng: Optional[random.Random] = None,
) -> Tuple[Optional[str], str]:
    """
    Returns (bot_name_with_ai_label_or_None, normalized_condition_key).
    """
    names = _bot_names(bots)
    raw = (condition or "").strip()
    key = raw.lower().replace(" ", "_").replace("-", "_") if raw else "_default"

    if not names:
        return None, key

    # Condition 2 — no disclosure
    if key in ("cond2", "condition2", "c2", "2", "control", "no_ai", "no_disclosure"):
        return None, "cond2"

    # Condition 1 — disclosure on a specific bot (counterbalanced between subjects)
    if key in ("cond1_a", "condition1_a", "c1_a", "1_a", "ai_a", "disclosure_a"):
        return ("a" if "a" in names else names[0]), "cond1_a"
    if key in ("cond1_b", "condition1_b", "c1_b", "1_b", "ai_b", "disclosure_b"):
        return ("b" if "b" in names else (names[1] if len(names) > 1 else names[0])), "cond1_b"

    # Match bot name directly: cond1_jamie etc.
    if key.startswith("cond1_") or key.startswith("c1_"):
        suffix = key.split("_", 1)[-1]
        for n in names:
            if n.lower() == suffix:
                return n, key

    # cond1 alone — random counterbalance (order effect across a vs b)
    if key in ("cond1", "condition1", "c1", "1", "disclosure"):
        r = rng or random
        pick = r.choice(names)
        return pick, f"cond1_{pick.lower()}"

    # Legacy / admin defaults
    if key in ("_default", ""):
        return None, "_default"

    return None, key


def apply_disclosure_to_bots(
    bots: List[Dict],
    ai_disclosed_bot: Optional[str],
) -> List[Dict]:
    """Return bot dicts with disclosed_ai_allowed set from group assignment."""
    out = []
    for b in bots:
        cfg = dict(b)
        name = cfg.get("name")
        cfg["disclosed_ai_allowed"] = bool(ai_disclosed_bot and name == ai_disclosed_bot)
        out.append(cfg)
    return out


def assign_group_disclosure(
    bots: List[Dict],
    condition: Optional[str],
    group_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist disclosure on group_info; return updated group_info."""
    ai_bot, norm = resolve_ai_disclosed_bot(bots, condition)
    group_info["ai_disclosed_bot"] = ai_bot
    group_info["study_condition"] = norm
    return group_info


def effective_bot_cfg(bot_cfg: Dict, group_info: Optional[Dict]) -> Dict:
    """Merge session bot config with per-group disclosure assignment."""
    cfg = dict(bot_cfg)
    if not group_info or "ai_disclosed_bot" not in group_info:
        return cfg
    ai_name = group_info.get("ai_disclosed_bot")
    cfg["disclosed_ai_allowed"] = bool(ai_name and cfg.get("name") == ai_name)
    return cfg
