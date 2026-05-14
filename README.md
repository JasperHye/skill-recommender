# Skill Recommender (skill-rec)

每天根据用户行为、领域偏好和生态热度，自动推荐最有价值的 Agent skill。

## 亮点

- 🧠 **画像自学习** — 从已安装 skill、工具使用习惯、对话主题自动推断偏好
- 🎯 **五维匹配** — 类别 + 工具链 + 复杂度 + 工作流互补 + 行为适应
- 🌍 **跨 Agent** — 适配 Hermes / Claude Code / OpenClaw / Codex / OpenCode
- 🛡️ **三层安全** — 来源可信度 + 元数据检查 + 模式扫描
- 🔀 **80/20 探索** — 4 天推匹配的，1 天推新领域
- 📊 **疲劳衰减** — 同类推太多会自动降低权重

## 使用

### 安装

1. 把整个目录放到 Agent 的 skills 路径下
2. Hermes：`cp -r skill-recommender ~/.hermes/skills/`

### 触发

说「推荐个 skill」「有什么新 skill 可用」或任何表达你想发现 skill 的意图。首次使用时系统会问你：要不要每天自动推。

### 每日推荐

回复「开启」即可创建每日定时任务，每天早上 10:00 自动推送。

## 文件结构

```
skill-recommender/
├── SKILL.md                  ← Agent 加载入口
├── PRD.md                    ← 产品需求文档
├── PLAN.md                   ← 开发计划
├── scripts/
│   ├── daily_job.py          ← cron 调用入口
│   ├── profiler.py           ← 画像引擎
│   ├── detector.py           ← Agent 类型探测
│   ├── ranker.py             ← 过滤 + 五维打分
│   ├── diversity.py          ← 多样性引擎
│   ├── security.py           ← 三层安全扫描
│   ├── reasoner.py           ← 个性化理由生成
│   └── state_store.py        ← JSON 持久化
├── data/
│   ├── state.json            ← 运行状态
│   ├── profile.json          ← 用户画像
│   ├── history.json          ← 推荐历史
│   └── complement_pairs.json ← 工作流互补关系
├── references/
│   └── 收集策略.md            ← 候选搜索指引
└── tests/                    ← 86 个测试
```

## 测试

```bash
python3 -m pytest tests/ -q
# 86 passed
```

## 版本

- 画像自学习 + 五维匹配 + 跨 Agent 适配（当前版本）
