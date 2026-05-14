# Skill Recommender

Agent 驱动的技能推荐协议。SKILL.md 定义决策规则由 Agent 执行，脚本只做确定性状态操作。

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

安装或更新后，Agent 应读取 `SKILL.md` 里的 `AGENT POST-INSTALL HOOK`。如果 `daily_rec_status` 还是 `unset`，Agent 会先调用 `scripts/feedback.py prompt-daily --source post_install` 记录“已询问”，再只询问一次是否开启每日推荐。用户回复「开启」后，Agent 调用 `scripts/feedback.py enable-daily` 并用返回的 cron 信息创建 `skill-recommender-daily` 定时任务。

### 触发

说「推荐个 skill」「有什么新工具」「帮我找个能...的 skill」。

安装后的 onboarding 会优先询问是否开启每日自动推送（默认关闭，需用户主动「开启」）。如果安装后没有执行 onboarding，首次合适的手动推荐流程也可以补问；但已处于 `prompted/enabled/disabled/unsupported` 时不会反复询问，并且一次只问一个授权问题。

### 每日推荐

回复「开启」→ Agent 创建 `skill-recommender-daily` cron 任务，每天早上 10:00 自动推送。

管理命令：「关闭每日推荐」「调整推荐偏好」

## 文件结构

```
skill-recommender/
├── SKILL.md                  ← Agent 加载入口（决策规则）
├── README.md                 ← 你正在看
├── scripts/
│   ├── candidate_filter.py   ← 去重 + 冷却 + 已安装过滤 + 每日限额
│   ├── security.py           ← 三层安全扫描（L1来源 + L2元数据 + L3模式）
│   ├── feedback.py           ← shown / accept / reject / enable-daily / disable-daily
│   └── state_store.py        ← JSON 持久化
├── data/
│   ├── state.json            ← 运行状态（tri-state daily_rec_status）
│   ├── history.json          ← 推荐历史
│   ├── profile.json          ← 用户画像（可选）
│   └── complement_pairs.json ← 工作流互补关系
└── references/
    └── 收集策略.md            ← 候选搜索渠道指引
```

## 脚本用法

```bash
# 候选过滤
python3 scripts/candidate_filter.py --mode manual|daily \
  --input candidates.json --state data/state.json --history data/history.json

# 安全扫描
python3 scripts/security.py --mode manual|daily --input filtered.json

# 反馈
python3 scripts/feedback.py shown --skill-id "..." --categories "devops,web"
python3 scripts/feedback.py accept --skill-id "..." --categories "devops,web"
python3 scripts/feedback.py reject --skill-id "..." --categories "devops"
python3 scripts/feedback.py prompt-daily --source manual
python3 scripts/feedback.py enable-daily
python3 scripts/feedback.py disable-daily
python3 scripts/feedback.py unsupported-daily
```

`shown` 应在输出推荐后立即调用；后续 `accept/reject` 会更新最近的 shown 记录，而不是新增重复推荐记录。拒绝默认是 14 天冷却，不是永久封禁。

## 版本

- **v3.0.0** — Agent-readable protocol：决策规则在 SKILL.md，脚本只做确定性操作（当前版本）
- v2.0.0 — 伪推荐引擎：脚本抢决策权（已废弃）
- v1.0.0 — 过滤+打分流水线（见 v1-archive/）
