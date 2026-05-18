"""状态持久化模块。

确定性操作：读写 JSON 文件。不做任何推理或默认策略决策。
关键规则：daily_rec_status 使用授权状态机
（unset | prompted | pending_schedule | enabled | disabled | unsupported）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


DEFAULT_STATE: Dict[str, Any] = {
    "user_id": "local-user",
    # "unset" = 未询问过
    # "prompted" = 已询问但用户未明确同意/拒绝
    # "pending_schedule" = 用户同意，但定时任务尚未确认创建成功
    # "enabled" = 用户同意且已确认存在定时任务
    # "disabled" = 用户拒绝/关闭
    # "unsupported" = 当前 Agent 不支持 cron/automation
    "daily_rec_status": "unset",
    "daily_rec_prompted_at": None,
    "daily_rec_prompt_source": None,
    "daily_rec_unsupported_at": None,
    "daily_schedule_pending_at": None,
    "daily_schedule_confirmed_at": None,
    "daily_schedule_failed_at": None,
    "daily_schedule_failure_reason": None,
    "daily_failure_notice_status": "unset",
    "daily_failure_notice_reason": None,
    "daily_failure_notice_last_shown_at": None,
    "auto_update_status": "ask",
    "last_update_check_at": None,
    "last_seen_remote_version": None,
    "last_update_notice_at": None,
    "update_notice_status": "unset",
    "push_time_local": "10:00",
    "timezone": None,
    "profile_version": 3,
    "accepted_skill_ids": [],
    "installed_skill_ids": [],
    "rejected_skill_ids": [],
    "last_actions": [],
    "accepted_categories": {},
    "scenario_memory": {
        "signals": [],
        "last_updated_at": None,
    },
    "daily_rotation": {
        "last_theme": None,
        "last_run_at": None,
    },
    "diversity_state": {
        "explore_counter": 0,
        "category_fatigue": {},
        "recent_boosted_category": None,
        "boost_expires": None,
    },
    "_installed_skills_meta": [],
}


def default_state_dir() -> Path:
    """Return the persistent state directory outside the skill install folder."""
    configured = os.environ.get("SKILL_RECOMMENDER_STATE_DIR")
    if configured:
        return Path(configured).expanduser()

    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        return Path(hermes_home).expanduser() / "state" / "skill-recommender"

    home = Path.home()
    hermes_dir = home / ".hermes"
    if hermes_dir.exists():
        return hermes_dir / "state" / "skill-recommender"

    return home / ".skill-recommender"


def default_state_path() -> Path:
    return default_state_dir() / "state.json"


def default_history_path() -> Path:
    return default_state_dir() / "history.json"


def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default.copy()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            merged = default.copy()
            merged.update(loaded)
            return merged
        return default.copy()
    except (json.JSONDecodeError, OSError):
        return default.copy()


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state(path: Path) -> Dict[str, Any]:
    """加载运行状态。首次使用时返回 DEFAULT_STATE（daily_rec_status="unset"）。"""
    return load_json(path, DEFAULT_STATE)


def load_history(path: Path) -> Dict[str, Any]:
    return load_json(path, {"recommendations": []})
