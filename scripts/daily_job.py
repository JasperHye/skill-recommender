"""每日推荐入口。

cron 任务调用的主流程。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# 将 scripts 目录加入 path，确保模块可导入
_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from profiler import build_profile, cold_start_category
from ranker import apply_filters, score_candidates, utc_now
from reasoner import generate_message
from detector import detect, agent_name, AgentCapabilities, AgentType
from state_store import load_state, load_history, save_json
from security import scan_candidates
from diversity import apply_diversity


def _load_candidates(path: Path) -> List[Dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload.get("candidates", [])
    if isinstance(payload, list):
        return payload
    return []


def run(args: argparse.Namespace) -> int:
    """执行一次完整推荐流程。"""
    now = datetime.fromisoformat(args.now) if args.now else utc_now()

    # 加载数据
    state = load_state(Path(args.state))
    history = load_history(Path(args.history))
    candidates = _load_candidates(Path(args.candidates))

    if not state.get("daily_rec_enabled", False):
        print("[silent] daily recommendation disabled")
        return 0

    if not candidates:
        print("[silent] no candidates available")
        return 0

    # Agent 探测
    agent_type, capabilities = detect()
    if args.verbose:
        print(f"[info] Agent: {agent_name(agent_type)} (tiers: {capabilities.tiers})")

    # 构建用户画像（Tier 1 only — Agent 负责传入 Tier 2/3 数据）
    # 实际 cron 运行时，Agent 应该先自行获取 tool_stats + sample_data 再调用此脚本。
    # 这里做文件本地调用，只用 Tier 1。
    installed_skills = state.get("_installed_skills_meta", [])
    profile = build_profile(
        installed_skills=installed_skills,
        state=state,
        agent_type=agent_type,
        capabilities=capabilities,
    )

    if args.verbose:
        print(f"[info] 画像: tech={profile['tech_level']}, "
              f"cold_start={profile['cold_start_round']}")

    # 过滤
    filtered = apply_filters(candidates, state, history, now)

    if not filtered.kept:
        print("[silent] all candidates filtered out")
        if args.verbose:
            for sid, reason in filtered.dropped:
                print(f"  - {sid}: {reason}")
        return 0

    # 三层安全扫描
    secured, blocked = scan_candidates(filtered.kept)
    if args.verbose and blocked:
        for b in blocked:
            print(f"[security] blocked: {b.get('name')} — risk={b.get('risk_level')}")

    if not secured:
        print("[silent] all candidates blocked by security")
        return 0

    # 五维打分
    installed_names = [s.get("name", "") for s in installed_skills]
    ranked = score_candidates(secured, profile, state, history, now, installed_names, args.context)

    if not ranked:
        print("[silent] no ranked candidates")
        return 0

    # 多样性调整
    ranked = apply_diversity(ranked, profile, state, history, now)

    top = ranked[0]
    threshold = float(args.threshold)
    total_score = top["scores"]["total_score"]

    # 冷启动特殊处理：降低阈值到 0.40
    if profile["cold_start_round"] > 0:
        threshold = min(threshold, 0.40)

    if total_score < threshold:
        if args.verbose:
            print(f"[silent] top score {total_score:.4f} < threshold {threshold:.2f}")
        return 0

    # 输出推荐
    print(generate_message(top, profile, installed_names))

    # Dry-run 输出调试信息
    if args.dry_run:
        print("\n[debug] 分数明细:")
        for k, v in top["scores"].items():
            print(f"  {k}: {v}")
        print(f"\n[debug] 过滤掉的 ({len(filtered.dropped)}):")
        for sid, reason in filtered.dropped:
            print(f"  - {sid}: {reason}")
        print(f"\n[debug] 所有候选排名:")
        for i, item in enumerate(ranked[:5]):
            print(f"  {i+1}. {item.get('name')} — {item['scores']['total_score']:.4f}")

    # 写入历史（非 dry-run）
    if not args.dry_run:
        history.setdefault("recommendations", []).append({
            "date": now.isoformat(),
            "skill_id": top.get("skill_id"),
            "name": top.get("name"),
            "categories": top.get("categories", []),
            "score": total_score,
            "scores_breakdown": top.get("scores", {}),
            "user_action": "shown",
        })
        save_json(Path(args.history), history)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="每日 skill 推荐任务")
    parser.add_argument(
        "--candidates",
        default=str(Path(__file__).resolve().parent.parent / "data" / "sample_candidates.json"),
        help="候选 JSON 路径",
    )
    parser.add_argument(
        "--state",
        default=str(Path(__file__).resolve().parent.parent / "data" / "state.json"),
        help="状态 JSON 路径",
    )
    parser.add_argument(
        "--history",
        default=str(Path(__file__).resolve().parent.parent / "data" / "history.json"),
        help="历史 JSON 路径",
    )
    parser.add_argument("--threshold", type=float, default=0.60)
    parser.add_argument("--now", default=None, help="ISO datetime")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--context", default=None, help="用户原始请求文本（用于关键词 boost）")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
