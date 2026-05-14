"""画像引擎。

从已安装 skill 元数据、Agent 工具统计、主动采样三个数据源
构建用户画像，并在新用户场景下执行冷启动。
"""

from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from detector import AgentCapabilities, AgentType, detect

# ── 工具 → 模式 → 领域 映射 ──────────────────────────────────

TOOL_MODE_MAP: Dict[str, Tuple[str, List[str]]] = {
    "terminal":    ("运维型",   ["devops", "automation", "cloud", "infrastructure"]),
    "browser":     ("调研型",   ["research", "web", "data", "scraping"]),
    "computer_use":("桌面自动化", ["productivity", "macos", "gui"]),
    "git":         ("开发型",   ["coding", "github", "ci-cd", "version-control"]),
    "file":        ("创作型",   ["content", "media", "writing", "documentation"]),
    "write_file":  ("创作型",   ["content", "media", "writing", "documentation"]),
    "read_file":   ("分析型",   ["code-review", "debugging", "inspection"]),
    "search_files":("分析型",   ["code-review", "debugging", "inspection"]),
    "web_search":  ("调研型",   ["research", "web", "data"]),
    "memory":      ("管理型",   ["productivity", "knowledge"]),
    "session_search":("回顾型", ["productivity", "knowledge"]),
    "cronjob":     ("自动化型", ["automation", "scheduling"]),
    "delegate_task":("协作型",  ["multi-agent", "coding"]),
    "vision":      ("视觉型",   ["media", "design", "image"]),
    "image_gen":   ("创作型",   ["media", "design", "image"]),
}

# 热门的初始探索类别（冷启动用）
COLD_START_CATEGORIES = [
    ["devops", "automation"],
    ["coding", "github"],
    ["productivity", "macos"],
]

DEFAULT_DOMAIN_WEIGHTS = {
    "coding": 0.25,
    "automation": 0.25,
    "devops": 0.15,
    "productivity": 0.15,
    "data": 0.10,
    "media": 0.05,
    "research": 0.05,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _merge_weights(
    base: Dict[str, float],
    update: Dict[str, float],
    weight: float,
) -> Dict[str, float]:
    """加权合并两个权重字典。"""
    merged = copy.deepcopy(base)
    for k, v in update.items():
        merged[k] = merged.get(k, 0) * (1 - weight) + v * weight
    # 归一化
    total = sum(merged.values())
    if total > 0:
        return {k: v / total for k, v in merged.items()}
    return merged


# ═════════════════════════════════════════════════════════════
# Tier 1: Skill 元数据推断
# ═════════════════════════════════════════════════════════════

def _tier1_domain_weights(installed_skills: List[Dict]) -> Dict[str, float]:
    """从已安装 skill 的 categories 推断领域权重。"""
    counter: Counter = Counter()
    for skill in installed_skills:
        for cat in skill.get("categories", []):
            counter[cat.lower()] += 1
    total = sum(counter.values())
    if total == 0:
        return copy.deepcopy(DEFAULT_DOMAIN_WEIGHTS)
    return {k: v / total for k, v in counter.items()}


def _tier1_tool_fingerprint(installed_skills: List[Dict]) -> Dict[str, float]:
    """从已安装 skill 的 required_toolsets 推断工具指纹。"""
    counter: Counter = Counter()
    for skill in installed_skills:
        for tool in skill.get("required_toolsets", []):
            counter[tool.lower()] += 1
    total = sum(counter.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counter.items()}


# ═════════════════════════════════════════════════════════════
# Tier 2: Agent 专属增强
# ═════════════════════════════════════════════════════════════

def _tier2_hermes_tool_stats(tool_stats: Optional[List[Dict]] = None) -> Dict[str, float]:
    """Hermes: 从 session_search 或 /insights 获取的工具统计。

    tool_stats 格式：[{"tool_name": "terminal", "count": 45}, ...]
    由 Agent 在执行时通过 session_search 自行获取后传入。
    """
    if not tool_stats:
        return {}
    total = sum(item.get("count", 0) for item in tool_stats)
    if total == 0:
        return {}
    return {item["tool_name"]: item["count"] / total for item in tool_stats}


def _tier2_claude_insights(output: Optional[str] = None) -> Dict[str, float]:
    """Claude Code: 解析 /insights CLI 输出。

    由 Agent 在执行时跑 claude /insights 后传入输出文本。
    从文本中提取工具名称和频率。
    """
    if not output:
        return {}
    # 简单解析：找 "tool" 或工具名相关的行
    # Claude Code 的 /insights 格式可能变化，这里做保守解析
    result: Dict[str, float] = {}
    for line in output.split("\n"):
        for tool_name in TOOL_MODE_MAP:
            if tool_name in line.lower():
                # 尝试提取数字
                import re
                nums = re.findall(r"\d+", line)
                if nums:
                    result[tool_name] = int(nums[-1])
    total = sum(result.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in result.items()}


def _tier2_openclaw_state() -> Dict[str, float]:
    """OpenClaw: 读 ~/.openclaw/ 状态文件。

    由 Agent 在执行时读取文件内容的简化实现。
    """
    return {}  # 默认返回空，Agent 自行处理


# ═════════════════════════════════════════════════════════════
# Tier 3: 主动采样
# ═════════════════════════════════════════════════════════════

def _tier3_sample(sample_data: Optional[List[Dict]] = None) -> Dict[str, float]:
    """从 Agent 自报的采样数据提取工具指纹。

    sample_data 格式：[{"tool": "terminal", "frequency": 0.50}, ...]
    由 Agent 执行时自行回答后传入。
    """
    if not sample_data:
        return {}
    result = {}
    for item in sample_data:
        tool = item.get("tool", "").lower()
        freq = float(item.get("frequency", 0))
        if tool and freq > 0:
            result[tool] = freq
    total = sum(result.values())
    if total > 0:
        return {k: v / total for k, v in result.items()}
    return {}


# ═════════════════════════════════════════════════════════════
# 冷启动
# ═════════════════════════════════════════════════════════════

def cold_start_round(state: Dict) -> int:
    """返回当前冷启动轮次（0 = 已完成冷启动）。

    冷启动策略：前 3 轮按顺序推不同领域的 skill。
    """
    if state.get("cold_start_complete", False):
        return 0
    return state.get("cold_start_round", 1)


def cold_start_category(state: Dict) -> Optional[List[str]]:
    """返回当前冷启动轮应该推荐的类别。"""
    round_num = cold_start_round(state)
    if round_num <= 0 or round_num > len(COLD_START_CATEGORIES):
        return None
    return COLD_START_CATEGORIES[round_num - 1]


def advance_cold_start(state: Dict) -> Dict:
    """推进冷启动轮次。"""
    state = copy.deepcopy(state)
    current = state.get("cold_start_round", 1)
    if current >= len(COLD_START_CATEGORIES):
        state["cold_start_complete"] = True
        state["cold_start_round"] = 0
    else:
        state["cold_start_round"] = current + 1
    return state


# ═════════════════════════════════════════════════════════════
# 主入口：构建画像
# ═════════════════════════════════════════════════════════════

def build_profile(
    installed_skills: Optional[List[Dict]] = None,
    tool_stats: Optional[List[Dict]] = None,
    sample_data: Optional[List[Dict]] = None,
    state: Optional[Dict] = None,
    agent_type: Optional[AgentType] = None,
    capabilities: Optional[AgentCapabilities] = None,
) -> Dict[str, Any]:
    """构建用户画像。

    Args:
        installed_skills: 已安装的 skill 列表（至少含 name, categories, required_toolsets）
        tool_stats: Tier 2 数据（Hermes: session_search 统计；Claude: /insights 输出解析结果）
        sample_data: Tier 3 主动采样数据
        state: 运行状态（用于冷启动判断）
        agent_type: Agent 类型（可选，自动探测）
        capabilities: Agent 能力（可选，自动探测）

    Returns:
        用户画像 dict
    """
    if agent_type is None or capabilities is None:
        agent_type, capabilities = detect()

    installed_skills = installed_skills or []
    state = state or {}

    # Tier 1: 始终启用
    domain_weights = _tier1_domain_weights(installed_skills)
    tool_fingerprint = _tier1_tool_fingerprint(installed_skills)

    tier_weights = {"tier1": 1.0}  # 默认只用 Tier 1

    # Tier 2: 按 Agent 类型选择
    if AgentType.HERMES in [agent_type] and capabilities.tool_analytics:
        t2 = _tier2_hermes_tool_stats(tool_stats)
        if t2:
            tool_fingerprint = _merge_weights(tool_fingerprint, t2, 0.5)
            tier_weights["tier2"] = 0.5
            tier_weights["tier1"] = 0.5

    elif agent_type == AgentType.CLAUDE_CODE:
        t2 = _tier2_claude_insights(
            tool_stats[0].get("output", "") if tool_stats else ""
        )
        if t2:
            tool_fingerprint = _merge_weights(tool_fingerprint, t2, 0.4)
            tier_weights["tier2"] = 0.4
            tier_weights["tier1"] = 0.6

    # Tier 3: 兜底
    if capabilities.tiers and 3 in capabilities.tiers:
        t3 = _tier3_sample(sample_data)
        if t3:
            tool_fingerprint = _merge_weights(tool_fingerprint, t3, 0.1)
            tier_weights["tier3"] = 0.1
            # 重新平衡
            total_w = sum(tier_weights.values())
            tier_weights = {k: v / total_w for k, v in tier_weights.items()}

    # 推断技术等级
    tech_level = _infer_tech_level(installed_skills)

    # 冷启动状态
    cs_round = cold_start_round(state)

    return {
        "profile_version": 2,
        "domain_weights": domain_weights,
        "tool_fingerprint": tool_fingerprint,
        "tech_level": tech_level,
        "cold_start_round": cs_round,
        "cold_start_complete": state.get("cold_start_complete", False),
        "agent_type": agent_type.value,
        "tier_weights": tier_weights,
        "last_updated": _utc_now().isoformat(),
    }


def _infer_tech_level(installed_skills: List[Dict]) -> str:
    """从已安装 skill 的复杂度推断用户技术水平。"""
    complexity_count = Counter()
    for s in installed_skills:
        c = s.get("complexity", "lightweight")
        complexity_count[c] += 1
    platform = complexity_count.get("platform", 0)
    framework = complexity_count.get("framework", 0)
    lightweight = complexity_count.get("lightweight", 0)

    if platform >= 3 or (platform >= 1 and framework >= 5):
        return "advanced"
    if framework >= 3 or platform >= 1:
        return "intermediate"
    return "beginner"


# ═════════════════════════════════════════════════════════════
# 命令行入口（测试用）
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json
    import sys

    # 测试：模拟一些已安装 skill
    test_skills = [
        {
            "name": "docker-compose",
            "categories": ["devops", "docker"],
            "required_toolsets": ["terminal", "docker"],
            "complexity": "framework",
        },
        {
            "name": "github-pr-workflow",
            "categories": ["coding", "github"],
            "required_toolsets": ["terminal", "git"],
            "complexity": "framework",
        },
        {
            "name": "web-scraper",
            "categories": ["web", "data"],
            "required_toolsets": ["browser", "web_search"],
            "complexity": "lightweight",
        },
        {
            "name": "code-reviewer",
            "categories": ["coding", "code-review"],
            "required_toolsets": ["terminal", "git", "read_file"],
            "complexity": "lightweight",
        },
        {
            "name": "spotify",
            "categories": ["media", "entertainment"],
            "required_toolsets": ["spotify"],
            "complexity": "lightweight",
        },
    ]

    agent_type, capabilities = detect()
    print(f"Agent 类型: {agent_type.value}")
    print(f"可用 Tier: {capabilities.tiers}")
    print()

    # 冷启动状态
    state = {"cold_start_complete": False, "cold_start_round": 1}

    profile = build_profile(
        installed_skills=test_skills,
        state=state,
        agent_type=agent_type,
        capabilities=capabilities,
    )

    print("=== 用户画像 ===")
    print(json.dumps(profile, indent=2, ensure_ascii=False))
