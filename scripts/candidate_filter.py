"""候选过滤器（v3）。

确定性操作：去重、冷却检查、已安装过滤、质量过滤、每日限额。
不做打分或排序 — 那是 Agent 根据 SKILL.md 做的事。

v3 关键变更：
- --mode daily：检查今天是否已有推荐，有则全部过滤
- name 二级去重：同一 skill 跨来源合并
- 拒绝按 last_actions 做 14 天冷却；rejected_skill_ids 仅作历史记录
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

SOURCE_PRIORITY: Dict[str, int] = {
    "clawhub": 5,
    "mcpmarket": 4,
    "smithery": 3,
    "glama": 2,
    "github": 2,
    "x": 1,
}

BLACKLIST_CATEGORIES = {"entertainment", "fortune", "astrology"}

DEFAULT_MIN_DESC_LEN = 20
DEFAULT_STALE_DAYS = 180
DEFAULT_DEDUP_WINDOW_DAYS = 30
DEFAULT_REJECT_COOLDOWN_DAYS = 14


# ═══════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _days_between(now: datetime, then: Optional[datetime]) -> int:
    if then is None:
        return 9999
    if now.tzinfo is None and then.tzinfo is not None:
        then = then.replace(tzinfo=None)
    elif now.tzinfo is not None and then.tzinfo is None:
        now = now.replace(tzinfo=None)
    return max(0, (now - then).days)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_zone(timezone_name: Optional[str]):
    if not timezone_name:
        return timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _date_key(value: datetime, timezone_name: Optional[str]) -> str:
    """Return a YYYY-MM-DD key in the user's configured timezone."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_get_zone(timezone_name)).strftime("%Y-%m-%d")


def _normalize_name(name: str) -> str:
    """归一化名称用于二级去重。"""
    return name.strip().lower().replace("-", " ").replace("_", " ")


# ═══════════════════════════════════════════════════════════
# 去重（两级）
# ═══════════════════════════════════════════════════════════

def dedupe(candidates: List[Dict]) -> List[Dict]:
    """两级去重：
    1. skill_id 完全匹配 → 保留可信度最高的来源
    2. 归一化 name 匹配 → 同样保留最优来源
    """
    # 第一级：skill_id
    by_id: Dict[str, Dict] = {}
    for c in candidates:
        sid = c.get("skill_id") or ""
        if not sid:
            continue
        current = by_id.get(sid)
        if current is None:
            by_id[sid] = c
            continue
        prev_priority = SOURCE_PRIORITY.get(str(current.get("source", "")).lower(), 0)
        now_priority = SOURCE_PRIORITY.get(str(c.get("source", "")).lower(), 0)
        if now_priority > prev_priority:
            by_id[sid] = c

    # 第二级：归一化 name（跨来源合并）
    by_name: Dict[str, Dict] = {}
    for c in by_id.values():
        norm = _normalize_name(c.get("name", ""))
        if not norm:
            continue
        current = by_name.get(norm)
        if current is None:
            by_name[norm] = c
        else:
            prev_priority = SOURCE_PRIORITY.get(str(current.get("source", "")).lower(), 0)
            now_priority = SOURCE_PRIORITY.get(str(c.get("source", "")).lower(), 0)
            if now_priority > prev_priority:
                by_name[norm] = c
            # 标记跨源
            by_name[norm]["cross_source_count"] = by_name[norm].get("cross_source_count", 1) + 1

    return list(by_name.values())


# ═══════════════════════════════════════════════════════════
# 每日限额检查
# ═══════════════════════════════════════════════════════════

def check_daily_quota(
    history: Dict,
    now: Optional[datetime] = None,
    timezone_name: Optional[str] = None,
) -> Tuple[bool, str]:
    """检查今天是否已经推荐过任何 skill。

    Returns:
        (已用尽, 原因说明)
    """
    if now is None:
        now = _now()
    today = _date_key(now, timezone_name)

    for item in history.get("recommendations", []):
        item_date = _parse_iso(item.get("date"))
        if item_date and _date_key(item_date, timezone_name) == today:
            action = item.get("user_action", "shown")
            return True, f"daily_quota_exhausted: 今天已推过 (action={action})"

    return False, ""


# ═══════════════════════════════════════════════════════════
# 过滤
# ═══════════════════════════════════════════════════════════

def filter_candidates(
    candidates: List[Dict],
    state: Dict,
    history: Dict,
    mode: str = "manual",
    now: Optional[datetime] = None,
    min_desc_len: int = DEFAULT_MIN_DESC_LEN,
    stale_days: int = DEFAULT_STALE_DAYS,
    dedup_window_days: int = DEFAULT_DEDUP_WINDOW_DAYS,
    reject_cooldown_days: int = DEFAULT_REJECT_COOLDOWN_DAYS,
) -> Dict[str, Any]:
    """过滤管道。

    Args:
        candidates: 候选列表
        state: 运行状态
        history: 推荐历史
        mode: "manual" | "daily" — daily 模式额外检查每日限额
        now: 当前时间
        ...

    Returns:
        {"kept": [...], "dropped": [{"skill_id": ..., "reason": ...}, ...]}
    """
    if now is None:
        now = _now()

    dropped: List[Dict] = []
    kept: List[Dict] = []

    # Layer 0: 每日限额（daily 模式）
    if mode == "daily":
        exhausted, reason = check_daily_quota(history, now, state.get("timezone"))
        if exhausted:
            # 所有候选都因每日限额被过滤
            return {
                "kept": [],
                "dropped": [{"skill_id": "__all__", "reason": reason}],
            }

    installed = set(state.get("installed_skill_ids", []))

    # 近期推荐过的（skill_id 维度）
    recent_recommended: Dict[str, datetime] = {}
    for item in history.get("recommendations", []):
        sid = item.get("skill_id")
        dt = _parse_iso(item.get("date"))
        if sid and dt:
            recent_recommended[sid] = dt

    # 近期拒绝的（从 last_actions 精确判断冷却时间）
    recent_rejected: Dict[str, datetime] = {}
    for action in state.get("last_actions", []):
        if action.get("action") == "reject":
            sid = action.get("skill_id")
            dt = _parse_iso(action.get("date"))
            if sid and dt:
                recent_rejected[sid] = dt

    for c in dedupe(candidates):
        sid = c.get("skill_id", "")
        name = c.get("name", "")
        url = c.get("url", "")
        desc = c.get("description", "")
        cats = {str(x).lower() for x in c.get("categories", [])}

        # Layer 1: 完整性
        if not sid or not name or not url or not desc:
            dropped.append({"skill_id": sid or name or "unknown", "reason": "missing_required_fields"})
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            dropped.append({"skill_id": sid, "reason": "invalid_url"})
            continue

        # Layer 2: 用户状态
        if sid in installed:
            dropped.append({"skill_id": sid, "reason": "already_installed"})
            continue

        rec_at = recent_recommended.get(sid)
        if rec_at and _days_between(now, rec_at) < dedup_window_days:
            dropped.append({"skill_id": sid, "reason": "recommended_recently"})
            continue

        rej_at = recent_rejected.get(sid)
        if rej_at and _days_between(now, rej_at) < reject_cooldown_days:
            dropped.append({"skill_id": sid, "reason": "rejected_recently"})
            continue

        # Layer 3: 质量
        if cats.intersection(BLACKLIST_CATEGORIES):
            dropped.append({"skill_id": sid, "reason": "blacklist_category"})
            continue
        if len(desc.strip()) < min_desc_len:
            dropped.append({"skill_id": sid, "reason": "description_too_short"})
            continue

        updated = _parse_iso(c.get("updated_at"))
        downloads = float(c.get("popularity", {}).get("downloads", 0) or 0)
        stars = float(c.get("popularity", {}).get("stars", 0) or 0)
        if _days_between(now, updated) > stale_days and (downloads + stars) < 50:
            dropped.append({"skill_id": sid, "reason": "stale_and_low_popularity"})
            continue

        kept.append(c)

    return {"kept": kept, "dropped": dropped}


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description="候选过滤：去重 + 冷却 + 已安装 + 质量 + 每日限额")
    parser.add_argument("--input", required=True, help="候选 JSON 文件路径")
    parser.add_argument("--state", required=True, help="状态 JSON 文件路径")
    parser.add_argument("--history", required=True, help="历史 JSON 文件路径")
    parser.add_argument("--mode", default="manual", choices=["manual", "daily"],
                        help="manual: 无每日限额 | daily: 今天已推过则全部过滤")
    parser.add_argument("--output", default=None, help="输出文件路径（默认 stdout）")
    parser.add_argument("--min-desc-len", type=int, default=DEFAULT_MIN_DESC_LEN)
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    args = parser.parse_args()

    candidates = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates", [])
    if not isinstance(candidates, list):
        print(json.dumps({"kept": [], "dropped": []}))
        return

    state = _load_json(Path(args.state), {})
    history = _load_json(Path(args.history), {"recommendations": []})

    result = filter_candidates(
        candidates, state, history,
        mode=args.mode,
        min_desc_len=args.min_desc_len,
        stale_days=args.stale_days,
    )

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
