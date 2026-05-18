"""反馈处理模块。

确定性操作：处理用户对推荐的反馈，读写状态文件。
不做任何推理或决策 — 那是 Agent 根据 SKILL.md 做的事。

关键规则：
- 新增 shown 子命令（推荐展示后立即记录）
- cron prompt 缩短，具体渠道留给 SKILL.md
- 移除冷启动轮次推进（冷启动由 Agent 根据 history 判空决定）
- 每日推荐授权改为显式状态机：unset -> prompted -> pending_schedule -> enabled
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from state_store import DEFAULT_STATE, default_history_path, default_state_path

# 项目根目录（skill-recommender/）
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
LEGACY_STATE_PATH = DATA_DIR / "state.json"
LEGACY_HISTORY_PATH = DATA_DIR / "history.json"

# cron 任务配置 — 只写最小信息，具体流程由 SKILL.md 定义
CRON_JOB_NAME = "skill-recommender-daily"
DEFAULT_PUSH_TIME_LOCAL = "10:00"
CRON_PROMPT = (
    "Load the skill-recommender skill and run the Daily 推荐流程 defined in SKILL.md. "
    "Use persistent state outside the skill install directory."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
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


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cron_schedule_from_push_time(push_time_local: str) -> str:
    """Convert HH:MM local scheduler time into a daily cron expression."""
    value = (push_time_local or DEFAULT_PUSH_TIME_LOCAL).strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", value):
        value = DEFAULT_PUSH_TIME_LOCAL
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        hour, minute = 10, 0
    return f"{minute} {hour} * * *"


def _migrate_legacy_json(target_path: Path, legacy_path: Path, default: Dict[str, Any]) -> None:
    """Copy legacy in-skill state to persistent storage once, when useful."""
    if target_path.exists() or not legacy_path.exists() or target_path == legacy_path:
        return
    legacy = _load_json(legacy_path, default)
    if legacy == default:
        return
    _save_json(target_path, legacy)


def _state_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path == default_state_path():
        _migrate_legacy_json(path, LEGACY_STATE_PATH, DEFAULT_STATE)
    return path


def _history_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path == default_history_path():
        _migrate_legacy_json(path, LEGACY_HISTORY_PATH, {"recommendations": []})
    return path


def _find_latest_shown(history: Dict[str, Any], skill_id: str) -> Optional[Dict[str, Any]]:
    """Return the latest pending shown record for a skill, if any."""
    for item in reversed(history.get("recommendations", [])):
        if item.get("skill_id") == skill_id and item.get("user_action") == "shown":
            return item
    return None


def _upsert_feedback_history(
    history: Dict[str, Any],
    skill_id: str,
    action: str,
    categories: Optional[List[str]] = None,
    skill_name: str = "",
    skill_url: str = "",
) -> bool:
    """Update the latest shown record; append only when no shown record exists.

    Returns True when an existing shown record was updated. Callers use this to
    avoid double-counting category shown totals after the required shown event.
    """
    now = _utc_now()
    item = _find_latest_shown(history, skill_id)
    if item is not None:
        item["user_action"] = action
        item["responded_at"] = now
        if skill_name and not item.get("name"):
            item["name"] = skill_name
        if skill_url and not item.get("url"):
            item["url"] = skill_url
        if categories and not item.get("categories"):
            item["categories"] = categories
        return True

    history.setdefault("recommendations", []).append({
        "date": now,
        "skill_id": skill_id,
        "name": skill_name,
        "url": skill_url,
        "categories": categories or [],
        "user_action": action,
    })
    return False


# ═══════════════════════════════════════════════════════════
# Actions
# ═══════════════════════════════════════════════════════════


def accept(
    state_path: Path,
    history_path: Path,
    skill_id: str,
    categories: Optional[List[str]] = None,
    skill_name: str = "",
    skill_url: str = "",
) -> None:
    """记录用户同意安装一个 skill。"""
    state = _load_json(state_path, DEFAULT_STATE)
    history = _load_json(history_path, {"recommendations": []})

    installed = state.setdefault("installed_skill_ids", [])
    if skill_id not in installed:
        installed.append(skill_id)

    accepted = state.setdefault("accepted_skill_ids", [])
    if skill_id not in accepted:
        accepted.append(skill_id)

    state.setdefault("last_actions", []).append({
        "skill_id": skill_id,
        "action": "accept",
        "date": _utc_now(),
    })

    updated_existing_shown = _upsert_feedback_history(
        history,
        skill_id,
        "accepted",
        categories=categories,
        skill_name=skill_name,
        skill_url=skill_url,
    )

    if categories:
        accepted_cats = state.setdefault("accepted_categories", {})
        for cat in categories:
            entry = accepted_cats.setdefault(cat.lower(), {"accepted": 0, "shown": 0})
            entry["accepted"] = entry.get("accepted", 0) + 1
            if not updated_existing_shown:
                entry["shown"] = entry.get("shown", 0) + 1

    _save_json(state_path, state)
    _save_json(history_path, history)

    print(f"[feedback] accepted: {skill_id}")


def reject(
    state_path: Path,
    history_path: Path,
    skill_id: str,
    categories: Optional[List[str]] = None,
    skill_name: str = "",
) -> None:
    """记录用户拒绝一个 skill。"""
    state = _load_json(state_path, DEFAULT_STATE)
    history = _load_json(history_path, {"recommendations": []})

    # Append-only audit history. Filtering uses last_actions timestamps so a
    # rejection cools down for 14 days instead of becoming a permanent ban.
    rejected = state.setdefault("rejected_skill_ids", [])
    if skill_id not in rejected:
        rejected.append(skill_id)

    state.setdefault("last_actions", []).append({
        "skill_id": skill_id,
        "action": "reject",
        "date": _utc_now(),
    })

    updated_existing_shown = _upsert_feedback_history(
        history,
        skill_id,
        "rejected",
        categories=categories,
        skill_name=skill_name,
    )

    if categories and not updated_existing_shown:
        accepted_cats = state.setdefault("accepted_categories", {})
        for cat in categories:
            entry = accepted_cats.setdefault(cat.lower(), {"accepted": 0, "shown": 0})
            entry["shown"] = entry.get("shown", 0) + 1

    _save_json(state_path, state)
    _save_json(history_path, history)

    print(f"[feedback] rejected: {skill_id}")


def shown(
    state_path: Path,
    history_path: Path,
    skill_id: str,
    categories: Optional[List[str]] = None,
    skill_name: str = "",
    skill_url: str = "",
) -> None:
    """记录推荐已展示给用户（用户看到了但还没回复）。

    必须在输出推荐后立刻调用，否则 history 不完整，
    导致「每天最多 1 个」「30 天去重」等逻辑失真。
    """
    state = _load_json(state_path, DEFAULT_STATE)
    history = _load_json(history_path, {"recommendations": []})

    existing_shown = _find_latest_shown(history, skill_id)

    # 更新类别 shown 计数。重复 shown 只刷新已有记录，不重复计数。
    if categories and existing_shown is None:
        accepted_cats = state.setdefault("accepted_categories", {})
        for cat in categories:
            entry = accepted_cats.setdefault(cat.lower(), {"accepted": 0, "shown": 0})
            entry["shown"] = entry.get("shown", 0) + 1

    if existing_shown is not None:
        existing_shown["date"] = _utc_now()
        if skill_name:
            existing_shown["name"] = skill_name
        if skill_url:
            existing_shown["url"] = skill_url
        if categories:
            existing_shown["categories"] = categories
    else:
        history.setdefault("recommendations", []).append({
            "date": _utc_now(),
            "skill_id": skill_id,
            "name": skill_name,
            "url": skill_url,
            "categories": categories or [],
            "user_action": "shown",
        })

    _save_json(state_path, state)
    _save_json(history_path, history)

    print(f"[feedback] shown: {skill_id}")


def enable_daily(state_path: Path) -> Dict[str, Any]:
    """准备开启每日推荐。返回 cron 创建所需信息，但不直接标记 enabled。"""
    state = _load_json(state_path, DEFAULT_STATE)
    state["daily_rec_status"] = "pending_schedule"
    state["daily_schedule_pending_at"] = _utc_now()
    state["daily_schedule_failed_at"] = None
    state["daily_schedule_failure_reason"] = None
    _save_json(state_path, state)

    result = {
        "status": "pending_schedule",
        "cron_job_name": CRON_JOB_NAME,
        "cron_schedule": _cron_schedule_from_push_time(state.get("push_time_local", DEFAULT_PUSH_TIME_LOCAL)),
        "cron_prompt": CRON_PROMPT,
        "cron_skills": ["skill-recommender"],
        "push_time_local": state.get("push_time_local", DEFAULT_PUSH_TIME_LOCAL),
        "timezone": state.get("timezone"),
        "timezone_note": "cron_schedule is interpreted in the scheduler's local timezone unless the platform supports explicit timezone configuration.",
        "next_step": "Create the automation, then run feedback.py confirm-daily-enabled only after creation succeeds.",
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def confirm_daily_enabled(state_path: Path) -> Dict[str, Any]:
    """定时任务确认创建成功后，才正式开启每日推荐。"""
    state = _load_json(state_path, DEFAULT_STATE)
    state["daily_rec_status"] = "enabled"
    state["daily_schedule_confirmed_at"] = _utc_now()
    state["daily_schedule_failed_at"] = None
    state["daily_schedule_failure_reason"] = None
    _save_json(state_path, state)

    result = {
        "status": "enabled",
        "cron_job_name": CRON_JOB_NAME,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def fail_daily_schedule(state_path: Path, reason: str = "schedule_create_failed") -> Dict[str, Any]:
    """记录定时任务创建失败，避免出现 enabled 但无任务。"""
    state = _load_json(state_path, DEFAULT_STATE)
    state["daily_rec_status"] = "prompted"
    state["daily_schedule_failed_at"] = _utc_now()
    state["daily_schedule_failure_reason"] = reason
    _save_json(state_path, state)

    result = {
        "status": "prompted",
        "reason": reason,
        "cron_job_name": CRON_JOB_NAME,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def prompt_daily(state_path: Path, source: str = "manual") -> Dict[str, Any]:
    """记录已经询问过每日推荐授权，避免 post-install 和 manual 重复追问。"""
    state = _load_json(state_path, DEFAULT_STATE)
    current_status = state.get("daily_rec_status", "unset")
    changed = current_status in {"", None, "unset"}

    if changed:
        state["daily_rec_status"] = "prompted"
        state["daily_rec_prompted_at"] = _utc_now()
        state["daily_rec_prompt_source"] = source
        _save_json(state_path, state)

    result = {
        "status": state.get("daily_rec_status", current_status),
        "changed": changed,
        "daily_rec_prompted_at": state.get("daily_rec_prompted_at"),
        "daily_rec_prompt_source": state.get("daily_rec_prompt_source"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def disable_daily(state_path: Path) -> Dict[str, Any]:
    """关闭每日推荐。"""
    state = _load_json(state_path, DEFAULT_STATE)
    state["daily_rec_status"] = "disabled"
    _save_json(state_path, state)

    result = {
        "status": "disabled",
        "cron_job_name": CRON_JOB_NAME,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def unsupported_daily(state_path: Path) -> Dict[str, Any]:
    """记录当前 Agent 环境不支持 cron/automation，避免每次都重复询问。"""
    state = _load_json(state_path, DEFAULT_STATE)
    state["daily_rec_status"] = "unsupported"
    state["daily_rec_unsupported_at"] = _utc_now()
    _save_json(state_path, state)

    result = {
        "status": "unsupported",
        "reason": "cron_unsupported",
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skill 推荐反馈处理")
    sub = parser.add_subparsers(dest="action", required=True)

    # accept
    p = sub.add_parser("accept", help="记录同意安装")
    p.add_argument("--skill-id", required=True)
    p.add_argument("--skill-name", default="")
    p.add_argument("--skill-url", default="")
    p.add_argument("--categories", default="")
    p.add_argument("--state", default=str(default_state_path()))
    p.add_argument("--history", default=str(default_history_path()))

    # reject
    p = sub.add_parser("reject", help="记录拒绝")
    p.add_argument("--skill-id", required=True)
    p.add_argument("--skill-name", default="")
    p.add_argument("--categories", default="")
    p.add_argument("--state", default=str(default_state_path()))
    p.add_argument("--history", default=str(default_history_path()))

    # shown
    p = sub.add_parser("shown", help="记录推荐已展示")
    p.add_argument("--skill-id", required=True)
    p.add_argument("--skill-name", default="")
    p.add_argument("--skill-url", default="")
    p.add_argument("--categories", default="")
    p.add_argument("--state", default=str(default_state_path()))
    p.add_argument("--history", default=str(default_history_path()))

    # enable-daily
    p = sub.add_parser("enable-daily", help="准备开启每日推荐并返回 cron 配置")
    p.add_argument("--state", default=str(default_state_path()))

    # confirm-daily-enabled
    p = sub.add_parser("confirm-daily-enabled", help="确认定时任务已创建成功，正式开启每日推荐")
    p.add_argument("--state", default=str(default_state_path()))

    # fail-daily-schedule
    p = sub.add_parser("fail-daily-schedule", help="记录定时任务创建失败")
    p.add_argument("--reason", default="schedule_create_failed")
    p.add_argument("--state", default=str(default_state_path()))

    # prompt-daily
    p = sub.add_parser("prompt-daily", help="记录已询问每日推荐授权")
    p.add_argument("--source", default="manual", choices=["post_install", "manual"])
    p.add_argument("--state", default=str(default_state_path()))

    # disable-daily
    p = sub.add_parser("disable-daily", help="关闭每日推荐")
    p.add_argument("--state", default=str(default_state_path()))

    # unsupported-daily
    p = sub.add_parser("unsupported-daily", help="记录当前环境不支持每日推荐定时任务")
    p.add_argument("--state", default=str(default_state_path()))

    return parser


def main() -> None:
    args = build_parser().parse_args()

    categories = [c.strip() for c in args.categories.split(",") if c.strip()] if getattr(args, "categories", "") else []
    state_path = _state_path(args.state) if hasattr(args, "state") else default_state_path()
    history_path = _history_path(args.history) if hasattr(args, "history") else default_history_path()

    if args.action == "accept":
        accept(state_path, history_path, args.skill_id, categories, args.skill_name, getattr(args, "skill_url", ""))
    elif args.action == "reject":
        reject(state_path, history_path, args.skill_id, categories, args.skill_name)
    elif args.action == "shown":
        shown(state_path, history_path, args.skill_id, categories, args.skill_name, getattr(args, "skill_url", ""))
    elif args.action == "enable-daily":
        enable_daily(state_path)
    elif args.action == "confirm-daily-enabled":
        confirm_daily_enabled(state_path)
    elif args.action == "fail-daily-schedule":
        fail_daily_schedule(state_path, args.reason)
    elif args.action == "prompt-daily":
        prompt_daily(state_path, args.source)
    elif args.action == "disable-daily":
        disable_daily(state_path)
    elif args.action == "unsupported-daily":
        unsupported_daily(state_path)


if __name__ == "__main__":
    main()
