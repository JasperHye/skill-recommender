"""状态持久化模块（v3）。

确定性操作：读写 JSON 文件。不做任何推理或默认策略决策。
v3 关键变更：daily_rec_status 改为授权状态机
（unset | prompted | enabled | disabled | unsupported）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_STATE: Dict[str, Any] = {
    "user_id": "local-user",
    # "unset" = 未询问过
    # "prompted" = 已询问但用户未明确同意/拒绝
    # "enabled" = 用户同意且应存在定时任务
    # "disabled" = 用户拒绝/关闭
    # "unsupported" = 当前 Agent 不支持 cron/automation
    "daily_rec_status": "unset",
    "daily_rec_prompted_at": None,
    "daily_rec_prompt_source": None,
    "push_time_local": "10:00",
    "timezone": "Asia/Shanghai",
    "profile_version": 3,
    "accepted_skill_ids": [],
    "installed_skill_ids": [],
    "rejected_skill_ids": [],
    "last_actions": [],
    "accepted_categories": {},
    "diversity_state": {
        "explore_counter": 0,
        "category_fatigue": {},
        "recent_boosted_category": None,
        "boost_expires": None,
    },
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
    """加载运行状态。首次使用时返回 DEFAULT_STATE（daily_rec_status="unset"）。"""
    return load_json(path, DEFAULT_STATE)


def load_history(path: Path) -> Dict[str, Any]:
    return load_json(path, {"recommendations": []})
