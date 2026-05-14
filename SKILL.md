---
name: skill-rec
description: 当用户想找新的 agent skill、发现可用技能、获得推荐、开启/管理每日 skill 推送时使用。响应明确的「推荐 skill」「有什么新 skill」「帮我找个能...的 skill」以及模糊的「最近有什么好用的工具」「有没有能自动...的」「我想探索新能力」「还有类似的吗」。也处理「开启每日推荐」「关闭每日推荐」「调整推荐偏好」等管理操作。不要等用户说出「推荐」或「skill」这些词才触发——只要表达想发现或获得新工具/能力的意图就应该用。
license: MIT
metadata:
  hermes:
    tags: [推荐, 技能发现, 自动化, 个性化]
  compatibility: [hermes, claude-code, openclaw, codex]
---

# 每日技能推荐器

Agent 驱动的技能推荐协议。决策规则写在 SKILL.md 里由 Agent 执行，脚本只做确定性状态操作（校验、去重、安全扫描、反馈写入）。

## AGENT POST-INSTALL HOOK

安装或更新本 skill 后，Agent 应执行一次轻量 onboarding，用来尽早开启每日推荐，但不能静默创建定时任务。

1. 读取 `data/state.json`。
2. 如果 `daily_rec_status == "enabled"`，不再询问。
3. 如果 `daily_rec_status == "disabled"`，不再询问，除非用户主动要求开启。
4. 如果 `daily_rec_status == "prompted"`，不重复询问，除非用户主动要求开启。
5. 如果 `daily_rec_status == "unsupported"`，不重复询问，除非用户主动要求开启且当前 Agent 已支持 cron/automation。
6. 如果 `daily_rec_status == "unset"`，先运行：
   ```bash
   python3 scripts/feedback.py prompt-daily --source post_install
   ```
   然后只问一个问题：
   「要不要开启每日推荐？我会每天早上 10:00 给你推荐一个适合你的实用 AI 自动化能力。回复「开启」我就帮你设置，回复「不用」就保持手动推荐。」
7. 提问后立即停止输出，等待用户回复。不要在同一条消息里推荐 skill、做基础能力诊断或询问其他授权。
8. 用户回复「开启」后，运行：
   ```bash
   python3 scripts/feedback.py enable-daily
   ```
   然后使用返回的 `cron_job_name`、`cron_schedule`、`cron_prompt` 创建 Agent cron/automation。
9. 用户回复「不用」或拒绝后，运行：
   ```bash
   python3 scripts/feedback.py disable-daily
   ```
10. 如果当前 Agent 没有 cron/automation 能力，说明无法自动创建定时任务，并运行：
   ```bash
   python3 scripts/feedback.py unsupported-daily
   ```

## 架构原则

1. **Agent 判断，脚本验证** — 上下文推理、冷启动策略、输出话术由 Agent 根据本文规则决定；脚本只处理机械操作
2. **可见即所用** — 只使用 Agent 当前实际可访问的上下文，不假装有不可见的历史
3. **证据透明** — 推荐理由必须说明依据来源（最多 5 类，见下）
4. **安全第一** — medium 风险不自动推，high 风险永不推

## 执行流程

### 路径 A：用户主动请求推荐（manual）

触发条件：用户说「推荐个 skill」「有什么新工具」「帮我找个能...的 skill」等。

```
Step 1: 收集上下文信号
Step 2: 获取候选（联网搜索 or 本地缓存）
Step 3: 脚本校验（去重 + 冷却 + 安全扫描）
Step 4: Agent 排序 + 选最优
Step 5: 输出推荐
Step 6: 处理反馈 → 调 feedback.py
```

### 路径 B：每日自动推送（daily）

触发条件：cron 调度触发。入口相同，但多了授权检查。

```
Step 0: 检查 state.daily_rec_status == "enabled"，否则静默退出
Step 1-6: 同 manual 流程
```

### Step 1: 收集上下文信号

从以下来源收集信号（按优先级），**每个推荐必须声明用了哪些**：

| # | 信号源 | 获取方式 |
|---|--------|----------|
| 1 | 用户当前请求中的关键词 | 直接从用户消息提取 |
| 2 | 当前 workspace / 项目类型 | 看当前目录、文件类型 |
| 3 | 已安装 skill 列表 | 用 `skills_list` 获取，提取 categories |
| 4 | 可用工具列表 | Agent 自身能力 |
| 5 | 候选来源和生态热度 | 搜索时获取的 stars/downloads |

**规则**：
- 证据缺失时跳过，不编造
- 冷启动用户（无历史推荐记录）：优先使用信号 1、2、3
- 有历史记录的用户：额外参考上次接受的类别

### Step 2: 获取候选

Agent 自行从以下渠道收集候选（使用 web_search / browser 工具）：

**主渠道**（按优先级）：
1. **ClawHub** — 搜索 `site:clawhub.ai skills trending` 或浏览器打开 clawhub.ai
2. **MCP Market** — 搜索 `site:mcpmarket.com skills`
3. **Smithery** — 搜索 `site:smithery.ai new skills`
4. **Glama** — 搜索 `site:glama.ai mcp servers`
5. **GitHub** — 搜索 `mcp server skill trending`（替代 X/Twitter，X 需要登录）

**策略**：
- 每个可用渠道取前 5 个候选
- 同一 skill 出现在多来源 → 保留可信度最高的来源
- 如果所有渠道不可用 → 用 `data/sample_candidates.json` 缓存兜底
- 候选 < 3 个时，降低最低分阈值

每个候选归一化为：
```json
{
  "skill_id": "source:name-lower",
  "name": "Skill Name",
  "url": "https://...",
  "source_code_url": "GitHub URL（可选，缺失会导致安全扫描降级）",
  "description": "一句话描述",
  "categories": ["cat1", "cat2"],
  "source": "clawhub|mcpmarket|smithery|glama|github",
  "updated_at": "ISO 8601",
  "popularity": {"downloads": 0, "stars": 0},
  "required_toolsets": ["从描述推断"],
  "complexity": "lightweight|framework|platform",
  "has_install_docs": true/false,
  "has_security_disclosure": true/false
}
```
> `source_code_url` / `has_install_docs` / `has_security_disclosure` 三字段影响安全扫描结果。缺失任一都会导致 risk_level 至少 medium。

### Step 3: 脚本校验

将候选列表写入临时文件，调用脚本做机械校验：

**手动推荐（manual）：**
```bash
python3 scripts/candidate_filter.py --mode manual --input /tmp/candidates.json --state data/state.json --history data/history.json
python3 scripts/security.py --mode manual --input /tmp/filtered.json
```

**每日推送（daily）：**
```bash
python3 scripts/candidate_filter.py --mode daily --input /tmp/candidates.json --state data/state.json --history data/history.json
python3 scripts/security.py --mode daily --input /tmp/filtered.json
```

`--mode daily` 的区别：
- `candidate_filter`：按 `state.timezone` 检查今天是否已推过任何 skill，有则全部过滤
- `security`：medium 风险候选进入 blocked（不通过）

脚本自动完成：
- **去重**：skill_id + 归一化 name 两级去重，跨来源合并
- **已安装过滤**：已在 `state.installed_skill_ids` 中的跳过
- **冷却过滤**：`last_actions` 中 14 天内拒绝过的跳过；30 天内推荐过的跳过。`rejected_skill_ids` 仅作历史记录，不永久封禁
- **质量过滤**：描述 < 20 字、黑名单类别 → 丢弃
- **每日限额**（daily 模式）：今天 history 中已有任何推荐记录 → 全部过滤

安全判定规则（脚本输出 risk_level）：

| risk_level | 手动推荐 | 每日推送 |
|------------|----------|----------|
| low | ✅ 可推 | ✅ 可推 |
| medium | ⚠️ 可推但标注风险 | ❌ 脚本自动过滤 |
| high | ❌ 脚本自动过滤 | ❌ 脚本自动过滤 |

> 安全风险只升不降：如果候选已有 risk_level，最终取 max(existing, scanned)。

### Step 4: Agent 排序

Agent 根据以下维度对 shortlist 排序（自然语言判断，不调脚本）：

1. **请求匹配度**：候选类别/描述是否命中用户请求关键词（权重最高）
2. **已安装互补性**：候选是否与已安装 skill 形成工作流互补
3. **工具链适配**：候选所需工具是否与 Agent 已有工具重叠
4. **生态热度**：stars/downloads 越高越好
5. **新鲜度**：最近更新的优先（但不要太旧，超过 180 天降权）

**冷启动策略**（无历史推荐记录的前几轮）：
- 优先推与已安装 skill 类别互补的方向
- 如果没有明确方向 → 推生态热度最高的
- 不再使用硬编码的 devops→coding→productivity 顺序

**多样性**（有历史记录后）：
- 如果同类 skill 连续推了 3 次以上 → 优先换方向
- 刚装了某类 skill 的 7 天内 → 临时偏好同类

### Step 5: 输出推荐

选得分最高的候选输出。格式：

```
📡 今日推荐

**【skill 名称】**

为什么推荐给你：<一句话，基于实际使用的证据>

能力亮点：<1-2 句>

工具链适配：该 skill 使用 <toolset>，与你的 <已有工具/已装 skill> 配合顺畅

来源：<URL>
安全状态：来源 <来源名> | 风险等级：<low/medium>

操作：回复「同意安装」「暂不安装」「关闭每日推荐」
```

**规则**：
- 如果没有合适候选 → 沉默，不发推荐
- 如果是 medium 风险且手动触发 → 追加一句「⚠️ 该 skill 来源可信度一般，安装前建议自行审查」
- 如果是每日推送且这是首次使用 → 消息末尾不追加询问（授权状态由 Step 0 处理）

### Step 6: 记录展示 + 处理反馈

**输出推荐后，立刻记录展示：**
```bash
python3 scripts/feedback.py shown --skill-id "clawhub:skill-name" --skill-name "Skill Name" --categories "devops,automation" --skill-url "https://..."
```
> 必须调用！否则 history 不完整，「每天最多 1 个」「30 天去重」等逻辑都会失真。

**收到用户回复后，调用 feedback.py：**

```bash
# 同意安装
python3 scripts/feedback.py accept --skill-id "clawhub:skill-name" --categories "devops,automation"
  → 更新最近的 shown 记录为 accepted，写入 installed/accepted，该类别 accepted +1

# 暂不安装
python3 scripts/feedback.py reject --skill-id "clawhub:skill-name" --categories "security"
  → 更新最近的 shown 记录为 rejected，写入 14 天冷却

# 记录已经询问过每日推荐
python3 scripts/feedback.py prompt-daily --source manual
  → 设 daily_rec_status = "prompted"

# 开启每日推荐
python3 scripts/feedback.py enable-daily
  → 设 daily_rec_status = "enabled"
  → Agent 随后用 cronjob 工具创建名为 skill-rec-daily 的定时任务

# 关闭每日推荐
python3 scripts/feedback.py disable-daily
  → 设 daily_rec_status = "disabled"
  → Agent 随后用 cronjob 工具删除 skill-rec-daily 定时任务

# 当前 Agent 不支持定时任务
python3 scripts/feedback.py unsupported-daily
  → 设 daily_rec_status = "unsupported"
```

## 每日推荐授权

每日推荐是核心能力，应优先在安装后通过 `[AGENT POST-INSTALL HOOK]` 询问开启。运行时仍需遵守以下规则：

1. 每日推送永远只有 `daily_rec_status == "enabled"` 时才运行
2. 如果安装后没有机会执行 post-install hook，且后续 manual 流程中发现 `daily_rec_status == "unset"`，可以先调用 `feedback.py prompt-daily --source manual`，再询问是否开启 daily
3. `prompted`、`enabled`、`disabled`、`unsupported` 状态下不自动重复询问 daily
4. 询问 daily 必须遵守 one-question-per-turn：如果当前回复已经在问安装推荐 skill 或补齐基础能力，不要同时询问 daily
5. 用户回复「开启」→ 调 `feedback.py enable-daily` + 创建 cron/automation
6. 用户回复「不用」→ 调 `feedback.py disable-daily`，只更新状态，不创建 cron
7. 当前 Agent 不支持定时任务 → 调 `feedback.py unsupported-daily`

## 硬规则

1. 每天最多推荐 1 个
2. 绝不未经同意自动安装
3. high 风险永不推荐；medium 风险只可手动推荐且必须标注
4. 无合格候选就沉默（不硬推）
5. 不用 markdown 表格
6. 推荐理由必须说明使用了哪几类证据（格式：「基于你装的 X 类 skill 和最近对 Y 的关注」）
7. 不声称使用不可见的历史数据

## 本地脚本

| 脚本 | 用途 | 类型 |
|------|------|------|
| `scripts/candidate_filter.py` | 去重 + 冷却 + 已安装过滤 | 确定性 |
| `scripts/security.py` | 来源可信度 + 元数据 + 模式扫描 | 确定性 |
| `scripts/feedback.py` | 处理用户反馈（accept/reject/enable/disable） | 确定性 |
| `scripts/state_store.py` | 状态/历史 JSON 读写 | 确定性 |

## 常见踩坑

1. **候选收集失败** → 检查渠道可访问性；使用备用搜索词；降级到本地缓存
2. **推荐不准** → 检查 Step 1 的信号收集是否完整；有历史后偏好会自动调整
3. **cron 不执行** → 用当前 Agent 的 cron list 查看任务状态；确认 daily_rec_status == "enabled"
4. **拒绝太多** → 可能是方向偏了，让用户说「调整推荐偏好」重新探索
