"""状态持久化模块（v2）。

从 v1 迁移，扩展以支持新版 state/profile/history schema。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_STATE: Dict[str, Any] = {
    "user_id": "local-user",
    "daily_rec_enabled": True,
    "push_time_local": "10:00",
    "timezone": "Asia/Shanghai",
    "cold_start_complete": False,
    "cold_start_round": 1,
    "profile_version": 2,
    "accepted_skill_ids": [],
    "installed_skill_ids": [],
    "rejected_skill_ids": [],
    "last_actions": [],
    "diversity_state": {
        "explore_counter": 0,
        "last_explore_date": None,
        "category_fatigue": {},
        "recent_boosted_category": None,
        "boost_expires": None,
    },
    "last_tier3_sample": None,
    "_installed_skills_meta": [],
}


def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default.copy()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default.copy()


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state(path: Path) -> Dict[str, Any]:
    return load_json(path, DEFAULT_STATE)


def load_history(path: Path) -> Dict[str, Any]:
    return load_json(path, {"recommendations": []})


def load_profile(path: Path) -> Dict[str, Any]:
    return load_json(path, {
        "profile_version": 2,
        "domain_weights": {},
        "tool_fingerprint": {},
        "tech_level": "beginner",
        "cold_start_round": 1,
        "cold_start_complete": False,
        "agent_type": "generic",
        "tier_weights": {"tier1": 1.0},
        "last_updated": None,
    })
