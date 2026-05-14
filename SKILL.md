---
name: skill-rec
description: 当用户想找新的 agent skill、发现可用技能、获得推荐、开启/管理每日 skill 推送时使用。响应明确的「推荐 skill」「有什么新 skill」「帮我找个能...的 skill」以及模糊的「最近有什么好用的工具」「有没有能自动...的」「我想探索新能力」「还有类似的吗」。也处理「开启每日推荐」「关闭每日推荐」「调整推荐偏好」等管理操作。不要等用户说出「推荐」或「skill」这些词才触发——只要表达想发现或获得新工具/能力的意图就应该用。自动适配多种 Agent 环境，基于用户画像实现个性化匹配。
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [推荐, 技能发现, 自动化, 个性化]
  compatibility: [hermes, claude-code, openclaw, codex]
---

# 每日技能推荐器

每天根据用户行为、领域偏好和生态热度，推荐一个最有价值的 skill。核心能力：画像自学习、五维匹配、跨 Agent 适配。

## 执行步骤

### 第一步：探测与初始化

1. 调用 `scripts/detector.py` 探测当前 Agent 类型和能力层级
2. 读取 `data/state.json`，如不存在则用默认值
3. 如果 `daily_rec_enabled` 未设置（首次使用）：
   - 正常输出本次推荐结果
   - 同时在推荐消息末尾追加一句询问：「另外，要不要我每天早上 10:00 自动给你推一个 skill？回复「开启」就行。」
   - 用户回复「开启」后：设置 `daily_rec_enabled=true`，用 Agent 的 cronjob 工具创建名为 `skill-rec-daily` 的定时任务
   - 用户忽略或说「不用」：设 `daily_rec_enabled=false`，只保留手动推荐能力
4. 如果 `daily_rec_enabled=true` 且无 cron 任务 → 静默补建 cron
5. 如果 `daily_rec_enabled=false` → 仅做手动推荐

### 第二步：构建用户画像

调用 `scripts/profiler.py` 的 `build_profile()`，传入：

- **installed_skills**：Agent 用 `skills_list` 获取已安装 skill，提取每个 skill 的 `categories`、`required_toolsets`、`complexity`
- **tool_stats**（Tier 2，可选）：Hermes 用 `session_search` 搜近 30 天 tool_name 分布；Claude Code 跑 `/insights` 解析
- **sample_data**（Tier 3，可选）：每 7 天问 Agent「你最近最常用的 5 个工具是什么？」，标准化传入
- **state**：当前运行状态

profiler 自动融合 Tier 1-3 数据，输出用户画像（领域权重 + 工具指纹 + 技术等级 + 冷启动状态）。

### 第三步：收集候选

按 `references/收集策略.md` 指引，Agent 自行用 web_search / browser 从 clawhub、mcpmarket、smithery、glama、X 五个渠道收集候选 skill。

每个候选归一化为标准格式（见 `references/数据格式.md`），去重后传给过滤管道。

### 第四步：过滤 + 安全扫描

1. **完整性**：name/url/description 必须齐备
2. **用户状态**：已安装/30天内推荐过/14天内拒绝过 → 跳过
3. **质量**：黑名单类别（娱乐/占星）、描述 < 20 字、超过 180 天没更新且低热度 → 丢弃
4. **安全**：三层防线（来源可信度 → 元数据检查 → AgentGuard 深度扫描）

详见 `references/过滤规则.md` 和 `references/安全规则.md`。

### 第五步：匹配打分

调用 `scripts/ranker.py` 的 `score_candidates()`，五项加权 + 关键词加成：

```python
总分 = 0.30 × 类别匹配 + 0.20 × 工具链匹配 + 0.15 × 复杂度匹配
     + 0.15 × 工作流互补 + 0.20 × 行为适应 - 风险惩罚 + 关键词加成
```

**关键词加成**：如果用户请求中包含具体技术词汇（如 Docker、Kubernetes），从请求中提取关键词，候选 skill 的 name/description/categories 每命中一个词 +0.04，上限 0.12。

详见 `references/排序规则.md`。

### 第六步：多样性调整

调用 `scripts/diversity.py`：

- **80/20 探索**：每 5 次推荐中 4 次匹配画像，1 次探索相邻领域
- **疲劳衰减**：同类连续推 4 次权重降到 0.55
- **已安装 boost**：刚装某类 7 天内临时 +20%

### 第七步：输出推荐

最高分 >= 0.60 才推荐。格式：

```
📡 今日推荐

**【skill 名称】**

为什么推荐给你：<个性化理由，基于匹配维度生成>

能力亮点：<1-2 句话>

工具链适配：该 skill 使用 <toolset>，与你的高频工具 <tool> 配合顺畅

来源：<URL>
安全状态：来源 <来源名> | 风险等级：low

操作：回复「同意安装」「暂不安装」「关闭每日推荐」
```

### 第八步：处理反馈

- 「同意安装」→ 安装 skill，画像该类别权重 +0.05，记录历史
- 「暂不安装」→ 该类别 14 天冷却
- 「关闭每日推荐」→ 停 cron，保留手动推荐
- 连续拒绝 3 次 → 自动降权 30%
- 连续接受 3 次 → 自动提权 20%

## 硬规则

1. 每天最多推荐 1 个
2. 绝不未经同意自动安装
3. 安全不通过绝不推荐
4. 无合格候选就沉默（不硬推）
5. 不用 markdown 表格
6. 冷启动阶段（前 3 轮）按 devops → coding → productivity 顺序推热门 skill

## 常见踩坑

1. **候选收集失败** → 检查各渠道是否可访问；使用备用搜索词；候选 < 3 个时降低阈值到 0.50
2. **画像不准确** → 新用户靠冷启动积累；老用户检查 installed_skills 是否完整传入
3. **Agent 探测失败** → 默认通用模式，依赖 Tier 1（skill 元数据）+ Tier 3（采样）
4. **cron 不执行** → 用当前 Agent 的 cron list 查看任务状态
5. **推荐被连续拒绝** → 检查 `domain_topic_weights` 是否偏离实际需求

## 本地脚本

| 脚本 | 用途 |
|------|------|
| `scripts/daily_job.py` | 推荐流程入口（cron 调用） |
| `scripts/profiler.py` | 画像引擎（Tier 1-3 + 冷启动） |
| `scripts/detector.py` | Agent 类型探测 |
| `scripts/ranker.py` | 过滤 + 多维度打分 |
| `scripts/diversity.py` | 探索预算 + 疲劳衰减 + boost |
| `scripts/security.py` | 三层安全防线 |
| `scripts/reasoner.py` | 个性化理由生成 |
| `scripts/state_store.py` | 状态读写 |

手动测试：
```bash
python3 scripts/profiler.py
```

## 参考文档

- `references/收集策略.md` — 五渠道搜索指引
- `references/过滤规则.md` — 过滤流水线参数
- `references/排序规则.md` — 五维打分公式
- `references/安全规则.md` — 三层安全防线
- `references/数据格式.md` — 数据 schema
