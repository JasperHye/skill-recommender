# Skill Recommender

Agent 驱动的技能推荐协议。SKILL.md 定义决策规则由 Agent 执行，脚本只做确定性状态操作。

当前仓库发布版本：`1.0.0`。版本信息见 `VERSION.json`。

## 设计原则

- **Agent 判断，脚本验证** — 上下文推理、排序、话术由 Agent 决定；脚本只做去重/安全/反馈
- **证据透明** — 推荐理由必须说明依据来源，不编造不可见数据
- **风险只升不降** — 安全扫描结果不会覆盖已有的更高风险标记

## 使用

### 安装

把整个目录放到 Agent 的 skills 路径下：

```bash
# Hermes
cp -r skill-recommender ~/.hermes/skills/

# Claude Code / OpenClaw / Codex 同理
```

安装或更新后，Agent 应读取 `SKILL.md` 里的 `AGENT POST-INSTALL HOOK`。如果外部持久状态里的 `daily_rec_status` 还是 `unset`，Agent 会先调用 `scripts/feedback.py prompt-daily --source post_install` 记录“已询问”，再只询问一次是否开启每日推荐。用户回复「开启」后，Agent 调用 `scripts/feedback.py enable-daily` 获取 cron 信息并进入 `pending_schedule`，创建 `skill-recommender-daily` 定时任务成功后再调用 `scripts/feedback.py confirm-daily-enabled`。

用户状态默认保存在 skill 目录之外：`~/.hermes/state/skill-recommender/state.json`。仓库内 `data/state.json` 只是模板，避免重新安装 skill 时把 daily 授权状态重置掉。

### 触发

说「推荐个 skill」「有什么新工具」「帮我找个能...的 skill」。

安装后的 onboarding 会优先询问是否开启每日自动推送（默认关闭，需用户主动「开启」）。如果安装后没有执行 onboarding，首次合适的手动推荐流程也可以补问；但已处于 `prompted/enabled/disabled/unsupported` 时不会反复询问，并且一次只问一个授权问题。

### 每日推荐

回复「开启」→ Agent 准备并创建 `skill-recommender-daily` cron 任务；创建成功后状态才会变成 `enabled`，每天早上 10:00 自动推送。

默认推送时间来自外部状态里的 `push_time_local`，格式为 `HH:MM`；`feedback.py enable-daily` 会据此生成 cron schedule。`timezone: null` 表示不假设用户时区，由当前 Agent/scheduler 的本地时区解释。

管理命令：「关闭每日推荐」「调整推荐偏好」

### 推荐后更新检查

Skill Recommender 会在 manual/daily 推荐完成后，使用当前 Agent 的原生搜索、WebFetch、浏览器或 GitHub connector 检查远端 `VERSION.json`。如果发现新版本，会在推荐内容末尾询问是否更新。

更新检查不会挡在推荐前面；没有无审批联网/读取能力时会静默跳过。用户明确回复「更新」后，Agent 才会使用平台原生 skill update / installer 能力，或在确认不会触发审批的情况下使用 git 更新。

## 文件结构

```
skill-recommender/
├── SKILL.md                  ← Agent 加载入口（决策规则）
├── README.md                 ← 你正在看
├── VERSION.json              ← 仓库发布版本
├── LICENSE                   ← MIT License
├── scripts/
│   ├── candidate_filter.py   ← 去重 + 冷却 + 已安装过滤 + 每日限额
│   ├── security.py           ← 三层安全扫描（L1来源 + L2元数据 + L3模式）
│   ├── feedback.py           ← shown / accept / reject / enable-daily / confirm-daily-enabled / disable-daily
│   └── state_store.py        ← JSON 持久化
├── data/
│   ├── state.json            ← 状态模板（真实用户状态在外部持久目录）
│   ├── history.json          ← 历史模板（真实推荐历史在外部持久目录）
│   ├── profile.json          ← 用户画像（可选）
│   └── complement_pairs.json ← 工作流互补关系
└── references/
    └── 收集策略.md            ← 候选搜索渠道指引
```

## 脚本用法

```bash
# 候选过滤
python3 scripts/candidate_filter.py --mode manual|daily \
  --input candidates.json \
  --state ~/.hermes/state/skill-recommender/state.json \
  --history ~/.hermes/state/skill-recommender/history.json

# 安全扫描
python3 scripts/security.py --mode manual|daily --input filtered.json

# 反馈
python3 scripts/feedback.py shown --skill-id "..." --categories "devops,web"
python3 scripts/feedback.py accept --skill-id "..." --categories "devops,web"
python3 scripts/feedback.py reject --skill-id "..." --categories "devops"
python3 scripts/feedback.py prompt-daily --source manual
python3 scripts/feedback.py enable-daily
python3 scripts/feedback.py confirm-daily-enabled
python3 scripts/feedback.py fail-daily-schedule --reason "schedule_create_failed"
python3 scripts/feedback.py disable-daily
python3 scripts/feedback.py unsupported-daily
```

`shown` 应在输出推荐后立即调用；后续 `accept/reject` 会更新最近的 shown 记录，而不是新增重复推荐记录。拒绝默认是 14 天冷却，不是永久封禁。

`feedback.py` 不传 `--state/--history` 时，会默认使用外部持久目录。可用 `SKILL_RECOMMENDER_STATE_DIR=/path/to/state-dir` 覆盖。

## 备注

脚本是可选 helper。推荐主流程应优先使用 Agent 原生搜索/浏览能力；本地脚本只在不触发审批时用于去重、安全扫描和状态记录。

## 作者

JasperHye — [X / Twitter](https://x.com/JasperHye)

## License

MIT License. Copyright (c) 2026 JasperHye.

You may use, copy, modify, and distribute this skill, including commercially, provided that the copyright notice and license notice are included in all copies or substantial portions of the software.

If you use or adapt this skill, attribution to this repository is appreciated:

https://github.com/JasperHye/skill-recommender
