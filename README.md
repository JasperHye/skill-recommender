# Skill Recommender

让 AI Agent 自动发现、评估、推荐新 skill 的智能推荐引擎。不用自己逛论坛搜——Agent 会根据你的使用习惯，每天推一个最值得装的 skill。

## 亮点

- 🧠 **画像自学习** — 从你装了哪些 skill、用了哪些工具、聊了什么话题，自动推断偏好
- 🎯 **五维匹配** — 不光看类别标签，还比对你常用的工具链、技术水平、工作流互补性
- 🔀 **80/20 探索** — 4 天推你擅长的领域，1 天推点你没试过的
- 🛡️ **安全扫描** — 来源可信度 + 元数据检查 + 模式扫描，三道防线
- 🌍 **跨 Agent 通用** — Hermes / Claude Code / OpenClaw / Codex 都能用
- 📊 **疲劳衰减** — 同类推太多会自动降权，不烦你

## 安装

> **一句话：把整个 `skill-rec` 文件夹复制到你的 Agent 的 skills 目录下。**
>
> 接下来 Agent 会自己读 `SKILL.md` 知道怎么运行。你只需要对 Agent 说「推荐个 skill」就能触发。

### Hermes

```bash
# 终端里执行
mkdir -p ~/.hermes/skills
cp -r skill-rec ~/.hermes/skills/

# 然后打开 Hermes，说：
# 「推荐个 skill」
```

### Claude Code

```bash
mkdir -p ~/.claude/skills
cp -r skill-rec ~/.claude/skills/

# 然后对 Claude Code 说：
# 「推荐个 skill」
```

### OpenClaw

```bash
mkdir -p ~/.openclaw/skills
cp -r skill-rec ~/.openclaw/skills/

# 对 OpenClaw 说：
# 「有什么新 skill 可以装？」
```

安装后不需要做任何配置。Agent 首次触发时会自动初始化，并问你要不要开启每天早上 10:00 的自动推送。

## 用法

### 手动触发

对 Agent 说下面任意一句：
- 「推荐个 skill」
- 「有什么新工具」
- 「帮我找个能自动部署的 skill」
- 「最近有什么好用的」

Agent 会根据你的画像，从 ClawHub 等渠道搜一圈，挑一个最匹配的推给你。

### 每日自动推送

首次使用时 Agent 会问你要不要开启。回复「开启」，之后每天早上 10:00 自动推一个。

管理命令：
- 「关闭每日推荐」— 停止自动推送
- 「调整推荐偏好」— 修改领域权重

## 工作原理

```
你的使用习惯
     ↓
画像引擎 → 分析你装了啥、用了啥
     ↓
候选收集 → 从 ClawHub / MCP Market / Smithery 等渠道搜
     ↓
过滤 + 安全扫描 → 去重、去已安装、去低质量、安全检查
     ↓
五维匹配打分 → 类别 + 工具链 + 复杂度 + 互补 + 行为适应
     ↓
多样性调整 → 80/20 探索 + 疲劳衰减
     ↓
推荐输出 → 带个性化理由 + 来源链接
```

## 文件结构

```
skill-rec/
├── SKILL.md              ← Agent 加载入口
├── README.md             ← 你正在看
├── scripts/
│   ├── profiler.py       ← 画像引擎
│   ├── ranker.py         ← 过滤 + 五维打分
│   ├── detector.py       ← Agent 类型探测
│   ├── diversity.py      ← 多样性引擎
│   ├── security.py       ← 三层安全扫描
│   ├── reasoner.py       ← 个性化理由生成
│   └── state_store.py    ← 状态持久化
├── data/                 ← 画像、历史、状态文件
└── references/           ← 收集策略、过滤规则等参考文档
```

## 常见问题

**装了没反应？**  
检查 `SKILL.md` 是否在 Agent 的 skills 路径下。Hermes 可以用 `skills_list` 确认。确认后直接说「推荐个 skill」触发。

**推荐的不准？**  
前 3 次是冷启动阶段，会按 devops → coding → productivity 顺序推热门 skill。3 次后画像积累起来就准了。

**怎么换 Agent？**  
直接把 `skill-rec` 文件夹复制到新 Agent 的 skills 目录就行。`data/` 里的画像文件也可以一起搬过去。

## 作者

[JasperHye](https://github.com/JasperHye)
