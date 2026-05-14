"""个性化理由生成引擎。

根据候选 skill 与用户画像的匹配维度，生成具体的推荐理由。
"""

from __future__ import annotations

from typing import Dict, List, Optional

# 维度最高分 → 对应的理由模板
TEMPLATES: Dict[str, str] = {
    "category_match": (
        "你最近在 {topics} 领域投入较多，{skill_name} 正好侧重这个方向"
    ),
    "toolchain_match": (
        "该 skill 主要使用 {tools}，与你最近高频使用的 {user_tools} 配合顺畅"
    ),
    "complexity_match": (
        "你当前的技能水平适合这个 {complexity} 级 skill，上手难度刚好"
    ),
    "workflow_complement": (
        "你已经装了 {installed}，{skill_name} 可以作为它的配套工具，实现 {flow} 流程"
    ),
    "behavior_adapt": (
        "你之前对 {similar_category} 类 skill 接受度很高，这个应该也适合你"
    ),
}


def _top_tools_from_fingerprint(fp: Dict[str, float], top_n: int = 3) -> str:
    """从工具指纹中提取 top N 工具名。"""
    if not fp:
        return "常用工具"
    sorted_items = sorted(fp.items(), key=lambda x: x[1], reverse=True)
    return "、".join(name for name, _ in sorted_items[:top_n])


def _top_categories_from_weights(weights: Dict[str, float], top_n: int = 2) -> str:
    """从领域权重中提取 top N 类别。"""
    if not weights:
        return "已有领域"
    sorted_items = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    return "、".join(name for name, _ in sorted_items[:top_n])


def _complexity_label(level: str) -> str:
    labels = {"lightweight": "轻量", "framework": "框架", "platform": "平台"}
    return labels.get(level, level)


def generate_reason(
    candidate: Dict,
    profile: Dict,
    installed_skill_names: Optional[List[str]] = None,
) -> str:
    """根据得分最高的维度生成个性化推荐理由。

    Args:
        candidate: 已评分的候选 skill（含 scores）
        profile: 用户画像
        installed_skill_names: 已安装 skill 名称列表

    Returns:
        一句中文推荐理由
    """
    scores = candidate.get("scores", {})
    if not scores:
        return "与你最近的使用习惯和领域方向匹配"

    # 找出最高分的维度
    scoring_dims = [
        ("category_match", scores.get("category_match", 0)),
        ("toolchain_match", scores.get("toolchain_match", 0)),
        ("complexity_match", scores.get("complexity_match", 0)),
        ("workflow_complement", scores.get("workflow_complement", 0)),
        ("behavior_adapt", scores.get("behavior_adapt", 0)),
    ]
    top_dim = max(scoring_dims, key=lambda x: x[1])
    dim_name, dim_score = top_dim

    skill_name = candidate.get("name", "这个 skill")
    categories = [c.lower() for c in candidate.get("categories", [])]

    # 冷启动特殊处理
    if profile.get("cold_start_round", 0) > 0 and not profile.get("cold_start_complete", False):
        return f"这是目前生态里口碑很好的 {categories[0] if categories else ''} 类 skill，适合探索"

    if dim_score < 0.4:
        return "与你最近的使用习惯和领域方向匹配"

    if dim_name == "category_match":
        topics = _top_categories_from_weights(profile.get("domain_weights", {}))
        return TEMPLATES["category_match"].format(topics=topics, skill_name=skill_name)

    if dim_name == "toolchain_match":
        tools = _top_tools_from_fingerprint(
            {t: 1.0 for t in candidate.get("required_toolsets", [])}, top_n=3
        )
        user_tools = _top_tools_from_fingerprint(
            profile.get("tool_fingerprint", {}), top_n=3
        )
        return TEMPLATES["toolchain_match"].format(
            tools=tools or "相关工具",
            user_tools=user_tools or "常用工具",
        )

    if dim_name == "complexity_match":
        complexity = candidate.get("complexity", "lightweight")
        return TEMPLATES["complexity_match"].format(
            complexity=_complexity_label(complexity),
        )

    if dim_name == "workflow_complement":
        installed = (installed_skill_names or ["常用 skill"])[0]
        flow = "完整的工作"
        if "coding" in categories or "github" in categories:
            flow = "开发-审查"
        elif "devops" in categories or "docker" in categories:
            flow = "开发-部署"
        elif "data" in categories or "web" in categories:
            flow = "采集-分析"
        return TEMPLATES["workflow_complement"].format(
            installed=installed,
            skill_name=skill_name,
            flow=flow,
        )

    if dim_name == "behavior_adapt":
        similar = _top_categories_from_weights(profile.get("domain_weights", {}))
        return TEMPLATES["behavior_adapt"].format(
            similar_category=similar,
        )

    return "与你最近的使用习惯和领域方向匹配"


def generate_message(top: Dict, profile: Dict, installed_skill_names: Optional[List[str]] = None) -> str:
    """生成完整的推荐输出消息。

    Args:
        top: 最高分候选（含 scores + risk_level）
        profile: 用户画像
        installed_skill_names: 已安装 skill 名称列表

    Returns:
        格式化的推荐消息
    """
    reason = generate_reason(top, profile, installed_skill_names)
    toolsets = ", ".join(top.get("required_toolsets", ["通用"]))
    source_name = top.get("source", "未知来源")
    source_url = top.get("url", "")
    risk = top.get("risk_level", "low")
    description = top.get("description", "")

    user_tools = _top_tools_from_fingerprint(profile.get("tool_fingerprint", {}), top_n=1)

    return (
        "\n📡 今日推荐\n\n"
        f"**{top.get('name')}**\n\n"
        f"为什么推荐给你：{reason}\n\n"
        f"能力亮点：{description}\n\n"
        f"工具链适配：该 skill 使用 {toolsets}，与你最近高频使用的 {user_tools} 配合顺畅\n\n"
        f"来源：{source_url}\n"
        f"安全状态：来源 {source_name} | 风险等级：{risk}\n\n"
        "操作：回复「同意安装」「暂不安装」「关闭每日推荐」"
    )
