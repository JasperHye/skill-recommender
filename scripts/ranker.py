"""匹配引擎：过滤 + 五维打分。

Phase 1 (v1) 保留的过滤管道 + v2 新增的五维匹配打分器。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ═══════════════════════════════════
# 常量
# ═══════════════════════════════════

SOURCE_PRIORITY: Dict[str, int] = {
    "clawhub": 5,
    "mcpmarket": 4,
    "smithery": 3,
    "glama": 2,
    "x": 1,
}

BLACKLIST_CATEGORIES = {"entertainment", "fortune", "astrology"}

# 默认互补关系路径
COMPLEMENT_PAIRS_PATH = Path(__file__).resolve().parent.parent / "data" / "complement_pairs.json"


# ═══════════════════════════════════
# 工具函数
# ═══════════════════════════════════

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _days_between(now: datetime, then: Optional[datetime]) -> int:
    if then is None:
        return 9999
    return max(0, (now - then).days)


def _load_complement_pairs() -> Dict[str, List[str]]:
    """加载工作流互补关系表。"""
    if COMPLEMENT_PAIRS_PATH.exists():
        try:
            return json.loads(COMPLEMENT_PAIRS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


# ═══════════════════════════════════
# 过滤
# ═══════════════════════════════════

@dataclass
class FilterResult:
    kept: List[Dict]
    dropped: List[Tuple[str, str]]  # (skill_id, reason)


def dedupe_by_priority(candidates: List[Dict]) -> List[Dict]:
    """同一 skill 出现在多个来源 → 保留优先级最高的。"""
    best: Dict[str, Dict] = {}
    for c in candidates:
        skill_id = c.get("skill_id") or c.get("name", "").strip().lower()
        if not skill_id:
            continue
        current = best.get(skill_id)
        if current is None:
            best[skill_id] = c
            continue
        prev_priority = SOURCE_PRIORITY.get(str(current.get("source", "")).lower(), 0)
        now_priority = SOURCE_PRIORITY.get(str(c.get("source", "")).lower(), 0)
        if now_priority > prev_priority:
            best[skill_id] = c
    return list(best.values())


def apply_filters(
    candidates: List[Dict],
    state: Dict,
    history: Dict,
    now: datetime,
    min_desc_len: int = 20,
    stale_days: int = 180,
    dedup_window_days: int = 30,
    reject_cooldown_days: int = 14,
) -> FilterResult:
    """四层过滤管道。"""
    dropped: List[Tuple[str, str]] = []
    kept: List[Dict] = []

    installed = set(state.get("installed_skill_ids", []))
    rejected = {
        x.get("skill_id"): x
        for x in state.get("last_actions", [])
        if x.get("action") == "reject"
    }

    recent_recommended: Dict[str, datetime] = {}
    for item in history.get("recommendations", []):
        sid = item.get("skill_id")
        dt = _parse_iso(item.get("date"))
        if sid and dt:
            recent_recommended[sid] = dt

    for c in dedupe_by_priority(candidates):
        sid = c.get("skill_id", "")
        name = c.get("name", "")
        url = c.get("url", "")
        desc = c.get("description", "")
        cats = {str(x).lower() for x in c.get("categories", [])}

        # Layer 1: 完整性
        if not sid or not name or not url or not desc:
            dropped.append((sid or name or "unknown", "missing_required_fields"))
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            dropped.append((sid, "invalid_url"))
            continue

        # Layer 2: 用户状态
        if sid in installed:
            dropped.append((sid, "already_installed"))
            continue
        recommended_at = recent_recommended.get(sid)
        if recommended_at and _days_between(now, recommended_at) < dedup_window_days:
            dropped.append((sid, "recommended_recently"))
            continue
        rejected_at = _parse_iso(rejected.get(sid, {}).get("date"))
        if rejected_at and _days_between(now, rejected_at) < reject_cooldown_days:
            dropped.append((sid, "rejected_recently"))
            continue

        # Layer 3: 质量
        if cats.intersection(BLACKLIST_CATEGORIES):
            dropped.append((sid, "blacklist_category"))
            continue
        if len(desc.strip()) < min_desc_len:
            dropped.append((sid, "description_too_short"))
            continue
        updated = _parse_iso(c.get("updated_at"))
        downloads = float(c.get("popularity", {}).get("downloads", 0) or 0)
        stars = float(c.get("popularity", {}).get("stars", 0) or 0)
        if _days_between(now, updated) > stale_days and (downloads + stars) < 50:
            dropped.append((sid, "stale_and_low_popularity"))
            continue

        kept.append(c)

    return FilterResult(kept=kept, dropped=dropped)


# ═══════════════════════════════════
# 打分器
# ═══════════════════════════════════

def _safe_ratio(num: float, den: float) -> float:
    if den <= 0:
        return 0.5
    return max(0.0, min(1.0, num / den))


# ── 1. 类别匹配（加权平均） ────────────────────────

def _category_match(profile: Dict, categories: List[str]) -> float:
    """候选类别与画像领域权重的加权平均。避免多分类 skill 分数膨胀。"""
    weights = profile.get("domain_weights", {})
    if not weights or not categories:
        return 0.5
    scores = [weights.get(cat, 0.0) for cat in categories]
    return max(0.0, min(1.0, sum(scores) / len(scores)))


# ── 2. 工具链匹配 ──────────────────────────────────

def _toolchain_match(profile: Dict, candidate: Dict) -> float:
    """skill 所需工具与用户工具指纹的匹配度。"""
    fp = profile.get("tool_fingerprint", {})
    toolsets = [t.lower() for t in candidate.get("required_toolsets", [])]
    if not toolsets or not fp:
        return 0.5
    scores = [fp.get(t, 0.0) for t in toolsets]
    return max(0.0, min(1.0, sum(scores) / len(scores)))


# ── 3. 复杂度匹配 ──────────────────────────────────

COMPLEXITY_MATRIX: Dict[str, Dict[str, float]] = {
    "beginner":     {"lightweight": 1.0, "framework": 0.5, "platform": 0.2},
    "intermediate": {"lightweight": 0.7, "framework": 1.0, "platform": 0.6},
    "advanced":     {"lightweight": 0.3, "framework": 0.7, "platform": 1.0},
}


def _complexity_match(profile: Dict, candidate: Dict) -> float:
    """skill 难度与用户技术水平匹配。"""
    user_level = profile.get("tech_level", "beginner")
    skill_complexity = candidate.get("complexity", "lightweight")
    matrix = COMPLEXITY_MATRIX.get(user_level, COMPLEXITY_MATRIX["beginner"])
    return matrix.get(skill_complexity, 0.5)


# ── 4. 工作流互补 ──────────────────────────────────

def _workflow_complement(profile: Dict, candidate: Dict, installed_skill_names: Optional[List[str]] = None) -> float:
    """检查 candidate 是否与已安装 skill 有工作流互补关系。"""
    if not installed_skill_names:
        return 0.5

    pairs = _load_complement_pairs()
    if not pairs:
        return 0.5

    candidate_name = (candidate.get("name", "") or "").lower()
    candidate_cats = [c.lower() for c in candidate.get("categories", [])]

    # 检查每个已安装 skill 的互补关系
    for installed_name in installed_skill_names:
        installed_lower = installed_name.lower()
        # 精确匹配：已安装 skill 名恰好是互补 key
        if installed_lower in pairs:
            complements = pairs[installed_lower]
            # 候选名或候选类别在互补列表中
            for comp in complements:
                if comp in candidate_name or candidate_name in comp:
                    return 1.0
                if any(comp in cat or cat in comp for cat in candidate_cats):
                    return 0.8
        # 模糊匹配：检查 installed skill 名是否包含互补 key 的子串
        for key, complements in pairs.items():
            if key in installed_lower or installed_lower in key:
                for comp in complements:
                    if comp in candidate_name or candidate_name in comp:
                        return 0.9
                    if any(comp in cat or cat in comp for cat in candidate_cats):
                        return 0.7

    return 0.5  # 无已知互补关系，中性分


# ── 5. 行为适应（3 因子） ──────────────────────────

def _behavior_adapt(state: Dict, categories: List[str]) -> float:
    """行为适应 = 类别接受率 × 0.5 + 安装后活跃度 × 0.3 + 同类留存率 × 0.2

    简化版：无活跃度/留存率数据时退化为纯类别接受率。
    """
    if not categories:
        return 0.5

    # 类别接受率
    accepted_cats = state.get("accepted_categories", {})
    rates = []
    for cat in categories:
        obj = accepted_cats.get(cat, {})
        rate = _safe_ratio(float(obj.get("accepted", 0)), float(obj.get("shown", 0)))
        rates.append(rate)
    category_rate = sum(rates) / len(rates) if rates else 0.5

    # 活跃度（简化：如果有 installed_skill_ids 就算"有活动"）
    installed_ids = state.get("installed_skill_ids", [])
    installed_boost = 0.0
    if installed_ids:
        # 最近安装的 skill 越多，可能活跃度越高
        accepted_count = len(state.get("accepted_skill_ids", []))
        installed_boost = min(0.3, accepted_count * 0.05)

    # 留存率（简化：已安装的 skill 确实还在用）
    retention = 0.5
    accepted_total = len(state.get("accepted_skill_ids", []))
    rejected_total = len(state.get("rejected_skill_ids", []))
    if accepted_total + rejected_total > 0:
        retention = _safe_ratio(accepted_total, accepted_total + rejected_total)

    return 0.5 * category_rate + 0.3 * installed_boost + 0.2 * retention


# ── 风险惩罚 ────────────────────────────────────────

def _risk_penalty(risk_level: str) -> float:
    if risk_level == "high":
        return 1.0
    if risk_level == "medium":
        return 0.15
    return 0.0


# ── 新鲜度 ──────────────────────────────────────────

def _freshness_score(now: datetime, updated_at: Optional[str]) -> float:
    dt = _parse_iso(updated_at)
    days = _days_between(now, dt)
    return max(0.0, min(1.0, 1 - (days / 180)))


def _popularity_score(candidate: Dict) -> float:
    pop = candidate.get("popularity", {})
    downloads = float(pop.get("downloads", 0) or 0)
    stars = float(pop.get("stars", 0) or 0)
    likes = float(pop.get("likes", 0) or 0)
    raw = downloads * 0.0005 + stars * 0.02 + likes * 0.01
    return max(0.0, min(1.0, raw))


def _cross_source_score(candidate: Dict) -> float:
    count = float(candidate.get("cross_source_count", 1) or 1)
    return max(0.0, min(1.0, count / 3))


def _novelty_score(history: Dict, now: datetime, categories: List[str]) -> float:
    latest_similar_days = 999
    for item in history.get("recommendations", []):
        item_cats = set(item.get("categories", []))
        if item_cats.intersection(categories):
            dt = _parse_iso(item.get("date"))
            if dt:
                latest_similar_days = min(latest_similar_days, _days_between(now, dt))
    return max(0.0, min(1.0, latest_similar_days / 14))


# ── Keyword boost ────────────────────────────────────

# Common stop words and short terms to filter out
_KEYWORD_STOP = {
    "的", "了", "是", "我", "有", "和", "就", "不", "人", "在", "都", "一个",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "or", "and", "not", "this",
    "that", "它", "这", "那", "你", "他", "她", "们", "什么", "怎么", "哪个",
    "可以", "能", "会", "要", "想", "让", "帮", "给", "用", "做", "找",
    "最近", "感觉", "有没有", "是不是", "那种", "一些", "几个", "免费", "好用",
}


def _extract_keywords(user_context: str) -> List[str]:
    """从用户请求中提取技术关键词。"""
    if not user_context:
        return []

    # 简单分词：按空格/标点/换行分割
    import re
    tokens = re.split(r'[\s,，。！？、；：""''（）\(\)\[\]【】\n\r\t]+', user_context.lower())
    keywords = []
    for token in tokens:
        token = token.strip()
        if len(token) < 2:
            continue
        if token in _KEYWORD_STOP:
            continue
        if token.isdigit():
            continue
        keywords.append(token)

    return keywords


def _keyword_boost(candidate: Dict, keywords: List[str]) -> float:
    """候选与用户关键词的匹配加分。每匹配一个词 +0.04，上限 0.12。"""
    if not keywords:
        return 0.0

    name = (candidate.get("name", "") or "").lower()
    desc = (candidate.get("description", "") or "").lower()
    cats = [c.lower() for c in candidate.get("categories", [])]
    search_text = f"{name} {desc} {' '.join(cats)}"

    matches = 0
    for kw in keywords:
        if kw in search_text:
            matches += 1

    if matches == 0:
        return 0.0
    return min(0.12, matches * 0.04)


# ═══════════════════════════════════
# 主打分入口
# ═══════════════════════════════════

def score_candidates(
    candidates: List[Dict],
    profile: Dict,
    state: Dict,
    history: Dict,
    now: datetime,
    installed_skill_names: Optional[List[str]] = None,
    user_context: Optional[str] = None,
) -> List[Dict]:
    """五维打分 + keyword boost + 排序。

    Args:
        candidates: 已过滤 + 安全扫描后的候选列表
        profile: 用户画像（来自 profiler.build_profile()）
        state: 运行状态
        history: 推荐历史
        now: 当前时间
        installed_skill_names: 已安装 skill 的名称列表（用于工作流互补）
        user_context: 用户原始请求文本（用于提取关键词 boost）

    Returns:
        按总分降序排列的候选列表，每个元素含 `scores` 字典。
    """
    scored: List[Dict] = []
    keywords = _extract_keywords(user_context or "")

    for c in candidates:
        categories = [str(x).lower() for x in c.get("categories", [])]

        # 五维打分
        category_m = _category_match(profile, categories)
        toolchain_m = _toolchain_match(profile, c)
        complexity_m = _complexity_match(profile, c)
        workflow_m = _workflow_complement(profile, c, installed_skill_names)
        behavior_a = _behavior_adapt(state, categories)

        # 趋势分（二分：新鲜度 + 热度 + 跨源）
        freshness = _freshness_score(now, c.get("updated_at"))
        popularity = _popularity_score(c)
        cross_source = _cross_source_score(c)
        trend = 0.4 * freshness + 0.4 * popularity + 0.2 * cross_source
        if str(c.get("source", "")).lower() == "x":
            trend = min(trend, 0.65)

        # 新颖分
        novelty = _novelty_score(history, now, categories)

        # 风险惩罚
        risk = c.get("risk_level", "low")
        penalty = _risk_penalty(risk)

        # v2 公式 + keyword boost
        kw_boost = _keyword_boost(c, keywords)
        total = (
            0.30 * category_m
            + 0.20 * toolchain_m
            + 0.15 * complexity_m
            + 0.15 * workflow_m
            + 0.20 * behavior_a
            - penalty
            + kw_boost
        )
        total = max(0.0, min(1.0, total))

        entry = c.copy()
        entry.update({
            "scores": {
                "category_match": round(category_m, 4),
                "toolchain_match": round(toolchain_m, 4),
                "complexity_match": round(complexity_m, 4),
                "workflow_complement": round(workflow_m, 4),
                "behavior_adapt": round(behavior_a, 4),
                "trend_score": round(trend, 4),
                "novelty_score": round(novelty, 4),
                "risk_penalty": round(penalty, 4),
                "keyword_boost": round(kw_boost, 4),
                "total_score": round(total, 4),
            }
        })
        scored.append(entry)

    # 排序
    def _sort_key(item: Dict):
        total = item["scores"]["total_score"]
        risk = item.get("risk_level", "low")
        risk_rank = {"low": 2, "medium": 1, "high": 0}.get(risk, 0)
        source_rank = SOURCE_PRIORITY.get(str(item.get("source", "")).lower(), 0)
        return (total, risk_rank, source_rank)

    return sorted(scored, key=_sort_key, reverse=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
