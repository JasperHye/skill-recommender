"""安全扫描模块（v2 三层防线）。

L1: 来源可信度
L2: 元数据完整性
L3: AgentGuard 深度扫描（可选）
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# ══════════════════════════════════════════════════════
# L1: 来源可信度
# ══════════════════════════════════════════════════════

SOURCE_TRUST: Dict[str, int] = {
    "clawhub":   5,  # 官方市场
    "mcpmarket": 4,  # 知名市场
    "smithery":  3,  # 知名市场
    "glama":     2,  # 较小市场
    "x":         1,  # 社交平台，不可靠
}

UNKNOWN_SOURCE_TRUST = 0  # 未知来源 → 自动 medium 风险


def _source_trust(source: str) -> int:
    """返回来源可信度分数。"""
    if not source:
        return UNKNOWN_SOURCE_TRUST
    return SOURCE_TRUST.get(source.lower(), UNKNOWN_SOURCE_TRUST)


# ══════════════════════════════════════════════════════
# L2: 元数据完整性
# ══════════════════════════════════════════════════════

# 必须满足至少 2 项
METADATA_CHECKS = [
    ("source_code_url", "有源码链接"),
    ("has_install_docs", "有安装文档"),
    ("has_security_disclosure", "有安全声明"),
]

REQUIRED_METADATA_COUNT = 2  # 至少满足 2 项才算完整


def _metadata_check(candidate: Dict) -> Tuple[int, List[str], List[str]]:
    """检查元数据完整性。

    Returns:
        (满足数, 满足项, 缺失项)
    """
    met = []
    missing = []
    for field, label in METADATA_CHECKS:
        if candidate.get(field):
            met.append(label)
        else:
            missing.append(label)
    return len(met), met, missing


# ══════════════════════════════════════════════════════
# L3: 危险模式扫描（基础版，AgentGuard 替代品）
# ══════════════════════════════════════════════════════

RISKY_PATTERNS = [
    r"eval\s*\(",
    r"exec\s*\(",
    r"os\.system\s*\(",
    r"subprocess\.\w+\s*\(.+shell\s*=\s*True",
    r"__import__\s*\(",
    r"compile\s*\(.+exec",
]

SENSITIVE_KEYWORDS = [
    ".ssh", ".env", "credentials", "id_rsa",
    "passwd", "shadow", "token", "secret",
]


def _pattern_scan(text: str) -> Tuple[List[str], List[str]]:
    """危险代码模式扫描。"""
    risky_hits: List[str] = []
    sensitive_hits: List[str] = []

    for pattern in RISKY_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            risky_hits.append(pattern)

    lower = text.lower()
    for kw in SENSITIVE_KEYWORDS:
        if kw in lower:
            sensitive_hits.append(kw)

    return risky_hits, sensitive_hits


# ══════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════

def scan_candidate(
    candidate: Dict,
    agentguard_available: bool = False,
    agentguard_scan_fn=None,
) -> Dict:
    """对单个候选执行三层安全扫描。

    Args:
        candidate: 候选 skill 数据
        agentguard_available: 是否有 AgentGuard
        agentguard_scan_fn: AgentGuard 扫描函数（可选）

    Returns:
        {"risk_level": "low"|"medium"|"high", "decision": "pass"|"filter", "details": [...]}
    """
    risk_level = "low"
    details: List[str] = []
    met_conditions = 0

    # L1: 来源可信度
    source = candidate.get("source", "")
    trust = _source_trust(source)
    if trust == 0:
        risk_level = "medium"
        details.append(f"L1: 未知来源 ({source or '无'})，可信度 0")
    elif trust <= 2:
        met_conditions += 1
        details.append(f"L1: 来源 {source} 可信度低 ({trust}/5)")
        if trust == 1:  # X/Twitter
            if risk_level == "low":
                risk_level = "medium"
    else:
        met_conditions += 1
        details.append(f"L1: 来源 {source} 可信 ({trust}/5)")

    # L2: 元数据完整性
    met_count, met_items, missing_items = _metadata_check(candidate)
    if met_count >= REQUIRED_METADATA_COUNT:
        met_conditions += 1
        details.append(f"L2: 元数据齐全 ({', '.join(met_items)})")
    else:
        details.append(f"L2: 元数据不完整 — 缺: {', '.join(missing_items)}")
        if risk_level == "low":
            risk_level = "medium"

    # L3: 模式扫描或 AgentGuard
    if agentguard_available and agentguard_scan_fn:
        # AgentGuard 深度扫描
        try:
            result = agentguard_scan_fn(candidate)
            if result.get("risk_level") == "high":
                return {
                    "risk_level": "high",
                    "decision": "filter",
                    "details": ["L3: AgentGuard 深度扫描 → HIGH 风险"] + details,
                    "risky_hits": [],
                    "sensitive_hits": [],
                }
            if result.get("risk_level") == "medium":
                if risk_level == "low":
                    risk_level = "medium"
                details.append("L3: AgentGuard 检测到中度风险")
            else:
                met_conditions += 1
                details.append("L3: AgentGuard 深度扫描通过")
        except Exception:
            details.append("L3: AgentGuard 扫描失败，跳过")
    else:
        # 基础模式扫描
        blob = "\n".join([
            str(candidate.get("name", "")),
            str(candidate.get("description", "")),
            str(candidate.get("raw_content", "")),
        ])
        risky_hits, sensitive_hits = _pattern_scan(blob)

        if risky_hits:
            return {
                "risk_level": "high",
                "decision": "filter",
                "details": [f"L3: 检测到危险模式: {', '.join(risky_hits)}"] + details,
                "risky_hits": risky_hits,
                "sensitive_hits": sensitive_hits,
            }

        if sensitive_hits:
            if risk_level == "low":
                risk_level = "medium"
            details.append(f"L3: 检测到敏感关键词: {', '.join(sensitive_hits)}")
        else:
            met_conditions += 1
            details.append("L3: 模式扫描无异常")

    # 最终判定
    if met_conditions >= 2:  # 至少通过两层
        decision = "pass"
    else:
        decision = "filter" if risk_level == "high" else "pass"

    return {
        "risk_level": risk_level,
        "decision": decision,
        "details": details,
        "risky_hits": [],
        "sensitive_hits": [],
    }


def scan_candidates(
    candidates: List[Dict],
    agentguard_available: bool = False,
    agentguard_scan_fn=None,
) -> Tuple[List[Dict], List[Dict]]:
    """批量安全扫描。

    Returns:
        (通过扫描的候选列表, 被拦截的候选列表)
    """
    passed = []
    blocked = []

    for c in candidates:
        result = scan_candidate(c, agentguard_available, agentguard_scan_fn)
        if result["decision"] == "filter":
            blocked.append({**c, **result})
        else:
            passed.append({**c, **result})

    return passed, blocked
