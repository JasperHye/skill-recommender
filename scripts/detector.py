"""Agent 类型探测模块。

自动识别当前运行的 Agent 环境（Hermes / Claude Code / OpenClaw / Codex 等），
返回 Agent 类型和支持的能力层级。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List


class AgentType(Enum):
    HERMES = "hermes"
    OPENCLAW = "openclaw"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    OPENCODE = "opencode"
    GENERIC = "generic"  # 兜底


@dataclass
class AgentCapabilities:
    """Agent 的能力矩阵"""
    session_search: bool = False          # 是否有跨会话搜索
    tool_analytics: bool = False          # 是否有工具调用统计
    skill_metadata: bool = False          # 是否有 skill 元数据
    file_state: bool = False              # 是否有可读的状态文件
    tiers: List[int] = field(default_factory=lambda: [1, 3])  # 可用的 Tier 列表


def detect() -> tuple[AgentType, AgentCapabilities]:
    """探测当前 Agent 类型并返回能力矩阵。

    Returns:
        (agent_type, capabilities)
    """
    home = Path.home()

    # Hermes: 检测 HERMES_HOME 或 ~/.hermes/
    if os.environ.get("HERMES_HOME") or (home / ".hermes").exists():
        return AgentType.HERMES, AgentCapabilities(
            session_search=True,
            tool_analytics=True,
            skill_metadata=True,
            file_state=True,
            tiers=[1, 2, 3],
        )

    # OpenClaw: 检测 ~/.openclaw/
    if (home / ".openclaw").exists():
        return AgentType.OPENCLAW, AgentCapabilities(
            session_search=False,
            tool_analytics=False,
            skill_metadata=True,
            file_state=True,
            tiers=[1, 2, 3],
        )

    # Claude Code: 检测 CLAUDE_CODE 或 ~/.claude/
    if os.environ.get("CLAUDE_CODE") or (home / ".claude").exists():
        return AgentType.CLAUDE_CODE, AgentCapabilities(
            session_search=False,
            tool_analytics=True,  # /insights 可用但需解析 CLI
            skill_metadata=True,
            file_state=False,
            tiers=[1, 2, 3],
        )

    # Codex: 检测 ~/.codex/
    if (home / ".codex").exists():
        return AgentType.CODEX, AgentCapabilities(
            session_search=False,
            tool_analytics=False,
            skill_metadata=False,
            file_state=False,
            tiers=[1, 3],
        )

    # OpenCode: 检测 ~/.opencode/
    if (home / ".opencode").exists():
        return AgentType.OPENCODE, AgentCapabilities(
            session_search=False,
            tool_analytics=False,
            skill_metadata=False,
            file_state=False,
            tiers=[1, 3],
        )

    # 兜底
    return AgentType.GENERIC, AgentCapabilities(
        session_search=False,
        tool_analytics=False,
        skill_metadata=False,
        file_state=False,
        tiers=[1, 3],
    )


def agent_name(agent_type: AgentType) -> str:
    """返回 Agent 的人类可读名称。"""
    names = {
        AgentType.HERMES: "Hermes Agent",
        AgentType.OPENCLAW: "OpenClaw",
        AgentType.CLAUDE_CODE: "Claude Code",
        AgentType.CODEX: "OpenAI Codex",
        AgentType.OPENCODE: "OpenCode",
        AgentType.GENERIC: "通用 Agent",
    }
    return names.get(agent_type, "未知 Agent")
