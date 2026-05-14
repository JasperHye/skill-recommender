"""安全扫描模块（v3 三层防线）。

L1: 来源可信度
L2: 元数据完整性
L3: 危险模式扫描 / AgentGuard 深度扫描

v3 关键变更：
- 风险只升不降：读取候选已有的 risk_level，最终取 max(existing, scanned)
- --mode daily：medium 风险进入 blocked
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# ══════════════════════════════════════════════════════
# 风险等级（数字越大越严重）
# ══════════════════════════════════════════════════════

RISK_ORDER: Dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def _max_risk(a: str, b: str) -> str:
    """取两个风险等级中较高的。"""
    return a if RISK_ORDER.get(a, 0) >= RISK_ORDER.get(b, 0) else b


# ══════════════════════════════════════════════════════
# L1: 来源可信度
# ══════════════════════════════════════════════════════

SOURCE_TRUST: Dict[str, int] = {
    "clawhub":   5,  # 官方市场
    "mcpmarket": 4,  # 知名市场
    "smithery":  3,  # 知名市场
    "glama":     2,  # 较小市场
    "github":    2,  # GitHub（项目质量参差不齐）
    "x":         1,  # 社交平台，不可靠
}

UNKNOWN_SOURCE_TRUST = 0  # 未知来源 → 自动 medium 风险


def _source_trust(source: str) -> int:
    if not source:
        return UNKNOWN_SOURCE_TRUST
    return SOURCE_TRUST.get(source.lower(), UNKNOWN_SOURCE_TRUST)


# ══════════════════════════════════════════════════════
# L2: 元数据完整性
# ══════════════════════════════════════════════════════

METADATA_CHECKS = [
    ("source_code_url", "有源码链接"),
    ("has_install_docs", "有安装文档"),
    ("has_security_disclosure", "有安全声明"),
]

REQUIRED_METADATA_COUNT = 2


def _metadata_check(candidate: Dict) -> Tuple[int, List[str], List[str]]:
    met = []
    missing = []
    for field, label in METADATA_CHECKS:
        if candidate.get(field):
            met.append(label)
        else:
            missing.append(label)
    return len(met), met, missing


# ══════════════════════════════════════════════════════
# L3: 危险模式扫描
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
# 扫描
# ══════════════════════════════════════════════════════

def scan_candidate(
    candidate: Dict,
    mode: str = "manual",
    agentguard_available: bool = False,
    agentguard_scan_fn=None,
) -> Dict:
    """对单个候选执行三层安全扫描。风险只升不降。

    Args:
        candidate: 候选 skill 数据（可能已有 risk_level）
        mode: "manual" | "daily" — daily 下 medium 进入 blocked
        agentguard_available: 是否有 AgentGuard
        agentguard_scan_fn: AgentGuard 扫描函数（可选）

    Returns:
        {"risk_level": "low"|"medium"|"high", "decision": "pass"|"filter", "details": [...]}
    """
    # 从候选已有风险等级起步（只升不降）
    existing = candidate.get("risk_level", "low")
    risk_level = existing if existing in RISK_ORDER else "low"
    details: List[str] = []
    met_conditions = 0

    # L1: 来源可信度
    source = candidate.get("source", "")
    trust = _source_trust(source)
    if trust == 0:
        risk_level = _max_risk(risk_level, "medium")
        details.append(f"L1: 未知来源 ({source or '无'})，可信度 0")
    elif trust <= 2:
        met_conditions += 1
        details.append(f"L1: 来源 {source} 可信度低 ({trust}/5)")
        if trust == 1:  # X/Twitter
            risk_level = _max_risk(risk_level, "medium")
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
        risk_level = _max_risk(risk_level, "medium")

    # L3: 模式扫描或 AgentGuard
    if agentguard_available and agentguard_scan_fn:
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
                risk_level = _max_risk(risk_level, "medium")
                details.append("L3: AgentGuard 检测到中度风险")
            else:
                met_conditions += 1
                details.append("L3: AgentGuard 深度扫描通过")
        except Exception:
            details.append("L3: AgentGuard 扫描失败，跳过")
    else:
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
            risk_level = _max_risk(risk_level, "medium")
            details.append(f"L3: 检测到敏感关键词: {', '.join(sensitive_hits)}")
        else:
            met_conditions += 1
            details.append("L3: 模式扫描无异常")

    # 最终判定：manual 可展示 medium（需标注风险），daily 只允许 low。
    if risk_level == "high":
        decision = "filter"
    elif risk_level == "medium" and mode == "daily":
        decision = "filter"
        details.append("MODE: daily 模式下 medium 风险自动拦截")
    else:
        decision = "pass"

    result = {
        "risk_level": risk_level,
        "decision": decision,
        "details": details,
        "risky_hits": [],
        "sensitive_hits": [],
    }
    # 记录原始候选风险 vs 扫描后风险
    if existing != risk_level:
        result["original_risk"] = existing
        result["details"].insert(0, f"风险升级: {existing} → {risk_level}")

    return result


def scan_candidates(
    candidates: List[Dict],
    mode: str = "manual",
    agentguard_available: bool = False,
    agentguard_scan_fn=None,
) -> Tuple[List[Dict], List[Dict]]:
    """批量安全扫描。

    Args:
        candidates: 候选列表
        mode: "manual" | "daily"
        agentguard_available: 是否有 AgentGuard
        agentguard_scan_fn: AgentGuard 扫描函数

    Returns:
        (通过的候选, 被拦截的候选)
    """
    passed = []
    blocked = []

    for c in candidates:
        result = scan_candidate(c, mode=mode, agentguard_available=agentguard_available, agentguard_scan_fn=agentguard_scan_fn)
        if result["decision"] == "filter":
            blocked.append({**c, **result})
        else:
            passed.append({**c, **result})

    return passed, blocked


# ══════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="三层安全扫描")
    parser.add_argument("--input", required=True, help="候选 JSON 文件路径")
    parser.add_argument("--output", default=None, help="输出文件路径（默认 stdout）")
    parser.add_argument("--mode", default="manual", choices=["manual", "daily"],
                        help="manual: 允许 medium 通过 | daily: medium 进入 blocked")
    parser.add_argument("--agentguard", action="store_true", help="启用 AgentGuard 深度扫描")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        candidates = data.get("kept", data.get("candidates", []))
    elif isinstance(data, list):
        candidates = data
    else:
        candidates = []

    passed, blocked = scan_candidates(candidates, mode=args.mode, agentguard_available=args.agentguard)

    result = {
        "passed": passed,
        "blocked": blocked,
        "summary": {
            "mode": args.mode,
            "total": len(candidates),
            "passed": len(passed),
            "blocked": len(blocked),
            "by_risk": {
                "high": len([b for b in blocked if b.get("risk_level") == "high"]),
                "medium": len([b for b in blocked if b.get("risk_level") == "medium"]),
            },
        },
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)
