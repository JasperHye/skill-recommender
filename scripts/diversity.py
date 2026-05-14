"""多样性引擎。

在匹配打分之后介入，调整排序以保证推荐不单调：
- 80/20 探索预算
- 类别疲劳衰减
- 已安装 boost
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# 相邻领域映射表：用于探索模式时拓展候选范围
ADJACENT_DOMAINS: Dict[str, List[str]] = {
    "devops":        ["cloud", "automation", "monitoring", "infrastructure"],
    "automation":    ["devops", "scheduling", "productivity"],
    "coding":        ["testing", "git", "code-review", "github"],
    "testing":       ["coding", "ci-cd", "code-review"],
    "github":        ["coding", "ci-cd", "code-review"],
    "data":          ["web", "research", "visualization"],
    "web":           ["data", "research", "scraping", "browser"],
    "media":         ["content", "design", "image", "writing"],
    "productivity":  ["macos", "automation", "note-taking"],
    "research":      ["data", "web", "writing", "arxiv"],
    "security":      ["devops", "audit", "compliance"],
    "ai":            ["mlops", "llm", "prompt-engineering", "evaluation"],
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        from ranker import _parse_iso as _p
        return _p(value)
    except ImportError:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)


def _days_between(now: datetime, then: Optional[datetime]) -> int:
    if then is None:
        return 9999
    return max(0, (now - then).days)


# ══════════════════════════════════════════════════════
# 1. 探索预算（80/20）
# ══════════════════════════════════════════════════════

EXPLORE_INTERVAL = 5  # 每 5 次推荐中有 1 次探索


def is_explore_turn(state: Dict) -> bool:
    """判断当前轮次是否应该探索相邻领域。"""
    div_state = state.get("diversity_state", {})
    counter = div_state.get("explore_counter", 0)
    return counter % EXPLORE_INTERVAL == EXPLORE_INTERVAL - 1


def get_explore_categories(profile: Dict) -> List[str]:
    """获取探索模式的目标类别（画像最高权重领域的相邻领域）。"""
    weights = profile.get("domain_weights", {})
    if not weights:
        return ["coding"]  # 兜底

    sorted_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    top_domain = sorted_weights[0][0]

    # 相邻领域
    adjacent = ADJACENT_DOMAINS.get(top_domain, ["productivity"])
    return adjacent


def apply_explore_boost(
    ranked: List[Dict],
    profile: Dict,
    state: Dict,
) -> List[Dict]:
    """如果是探索轮次，给相邻领域候选加分。"""
    if not is_explore_turn(state):
        return ranked

    explore_cats = set(get_explore_categories(profile))

    for item in ranked:
        item_cats = {c.lower() for c in item.get("categories", [])}
        overlap = item_cats.intersection(explore_cats)
        if overlap:
            # 探索 boost：匹配分 +0.10
            total = item["scores"]["total_score"]
            item["scores"]["total_score"] = min(1.0, total + 0.10)
            item["scores"]["explore_boost"] = round(0.10, 4)

    # 重新排序
    def _sort_key(item: Dict) -> float:
        return item["scores"]["total_score"]

    return sorted(ranked, key=_sort_key, reverse=True)


# ══════════════════════════════════════════════════════
# 2. 类别疲劳衰减
# ══════════════════════════════════════════════════════

FATIGUE_FACTORS = [1.0, 0.85, 0.70, 0.55]  # 连续推同类第 N 次的衰减系数


def _category_streak(history: Dict, category: str) -> int:
    """计算某类别最近连续推荐的次数。"""
    recs = history.get("recommendations", [])
    streak = 0
    # 正序遍历（假设 recs 按时间从新到旧排列）
    for rec in recs:
        rec_cats = {c.lower() for c in rec.get("categories", [])}
        if category.lower() in rec_cats:
            streak += 1
        else:
            break
    return streak


def _category_total_14d(history: Dict, category: str, now: datetime) -> int:
    """计算某类别最近 14 天推荐的总次数。"""
    recs = history.get("recommendations", [])
    count = 0
    for rec in recs:
        rec_date = _parse_iso(rec.get("date"))
        if rec_date and _days_between(now, rec_date) <= 14:
            rec_cats = {c.lower() for c in rec.get("categories", [])}
            if category.lower() in rec_cats:
                count += 1
    return count


def apply_fatigue(
    ranked: List[Dict],
    history: Dict,
    now: datetime,
) -> List[Dict]:
    """对同类连续推荐的候选施加疲劳衰减。"""
    for item in ranked:
        cats = [c.lower() for c in item.get("categories", [])]
        if not cats:
            continue

        # 取最严重的衰减
        worst_factor = 1.0
        for cat in cats:
            streak = _category_streak(history, cat)
            factor = FATIGUE_FACTORS[min(streak, len(FATIGUE_FACTORS) - 1)]

            # 14 天内总次数也影响衰减
            total_14d = _category_total_14d(history, cat, now)
            if total_14d >= 5:
                factor *= 0.8

            worst_factor = min(worst_factor, factor)

        if worst_factor < 1.0:
            total = item["scores"]["total_score"]
            item["scores"]["total_score"] = max(0.0, total * worst_factor)
            item["scores"]["fatigue_factor"] = round(worst_factor, 4)

    # 重新排序
    return sorted(ranked, key=lambda x: x["scores"]["total_score"], reverse=True)


# ══════════════════════════════════════════════════════
# 3. 已安装 boost
# ══════════════════════════════════════════════════════

BOOST_DURATION_DAYS = 7
BOOST_WEIGHT = 0.20


def apply_installed_boost(
    ranked: List[Dict],
    state: Dict,
    now: datetime,
) -> List[Dict]:
    """如果用户刚安装了某类 skill，给同类候选临时加分。"""
    div_state = state.get("diversity_state", {})
    boosted_cat = div_state.get("recent_boosted_category")
    boost_expires = _parse_iso(div_state.get("boost_expires"))

    # 检查 boost 是否过期
    if not boosted_cat or not boost_expires:
        return ranked

    if _days_between(now, boost_expires) > BOOST_DURATION_DAYS or now > boost_expires:
        return ranked

    for item in ranked:
        cats = {c.lower() for c in item.get("categories", [])}
        if boosted_cat.lower() in cats:
            total = item["scores"]["total_score"]
            item["scores"]["total_score"] = min(1.0, total + BOOST_WEIGHT)
            item["scores"]["installed_boost"] = round(BOOST_WEIGHT, 4)

    return sorted(ranked, key=lambda x: x["scores"]["total_score"], reverse=True)


# ══════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════

def apply_diversity(
    ranked: List[Dict],
    profile: Dict,
    state: Dict,
    history: Dict,
    now: Optional[datetime] = None,
) -> List[Dict]:
    """应用所有多样性调整：探索 boost → 疲劳衰减 → 已安装 boost。

    Args:
        ranked: 已打分排序的候选列表
        profile: 用户画像
        state: 运行状态（含 diversity_state）
        history: 推荐历史
        now: 当前时间

    Returns:
        调整后的排序列表
    """
    if now is None:
        now = _utc_now()

    # 第一步：探索 boost（如果是探索轮）
    ranked = apply_explore_boost(ranked, profile, state)

    # 第二步：疲劳衰减
    ranked = apply_fatigue(ranked, history, now)

    # 第三步：已安装 boost
    ranked = apply_installed_boost(ranked, state, now)

    # 递增探索计数器
    div_state = state.setdefault("diversity_state", {})
    div_state["explore_counter"] = div_state.get("explore_counter", 0) + 1

    return ranked


def record_installation(state: Dict, categories: List[str]) -> Dict:
    """记录一次 skill 安装，触发 7 天 boost。"""
    import copy
    state = copy.deepcopy(state)
    div_state = state.setdefault("diversity_state", {})
    if categories:
        div_state["recent_boosted_category"] = categories[0]
        div_state["boost_expires"] = _utc_now().isoformat()
    return state
