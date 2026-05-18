---
name: skill-recommender
description: 当用户想使用 Skill Recommender 查找新的 agent skill、发现可用技能、获得推荐、开启或管理每日 skill 推送时使用。响应明确的「推荐 skill」「有什么新 skill」「帮我找个能...的 skill」以及模糊的「最近有什么好用的工具」「有没有能自动...的」「我想探索新能力」「还有类似的吗」。也处理「开启每日推荐」「关闭每日推荐」「调整推荐偏好」等管理操作。不要等用户说出「推荐」或「skill」这些词才触发——只要表达想发现或获得新工具/能力的意图就应该用。
license: MIT
metadata:
  hermes:
    tags: [推荐, 技能发现, 自动化, 个性化]
  compatibility: [hermes, claude-code, openclaw, codex]
---

# 每日技能推荐器

Agent 驱动的技能发现协议。Skill Recommender 面向 Hermes、OpenClaw、Claude Code、Codex 和定制 Agent；不要按平台名称硬编码流程，要按当前 Agent 实际可用能力执行。

## 核心原则

1. **Agent 判断，helper 增强**：上下文理解、搜索策略、排序和话术由 Agent 执行；本地脚本只是可选 helper。
2. **No-approval runtime**：manual/daily 推荐主路径不得触发当前 Agent 的命令或权限审批。
3. **实时发现，不内置候选池**：不要用 `data/sample_candidates.json` 作为线上兜底；它只用于开发测试。
4. **场景驱动，但要有种草感**：推荐从当前任务、长期场景、能力缺口、热门趋势和用户“想试一下”的冲动出发，不从已安装列表出发。
5. **趋势和好玩值得被看见**：daily 推荐可以主动发现热门、日常、有趣的新能力，但不能覆盖安全和实际价值。
6. **已安装不等于偏好**：已安装 skill 只用于去重、判断已有能力、覆盖关系和最终 tie-breaker。
7. **可见即所用**：只使用当前真实可见的用户请求、工具、网页、候选元数据和状态。
8. **安全只升不降**：high 永不推荐；daily 只推 low；manual 可展示 medium，但必须说明风险。
9. **One question per turn**：安装授权、daily 开启、失败提醒配置不要塞在同一条回复里。
10. **先推荐，后更新**：版本检查只能在推荐完成后作为附加提醒，不得阻断 manual/daily 主流程。

## Agent Capability Contract

启动 manual 或 daily 流程前，先识别当前 Agent 的能力。不要假设平台一定有某个工具名。

| 能力 | 例子 | 用途 | 缺失时 |
|------|------|------|--------|
| `SearchCapability` | `web_search`、`search`、`search_web`、`web_extract`、`WebSearch`、`WebFetch`、搜索 MCP | 直接搜索候选来源 | 尝试浏览器搜索 |
| `BrowserCapability` | `browser_navigate`、`browser_snapshot`、`open_url`、`fetch_url`、browser/Playwright MCP | 打开搜索页和候选详情页 | manual 引导配置；daily 失败提醒 |
| `SafeLocalHelperCapability` | 运行 `scripts/*.py` 且不触发审批 | 去重、安全扫描、状态写入增强 | Agent 按本文规则自行过滤 |
| `StateCapability` | memory/state、skill state、免审批本地 JSON | 记录 shown、反馈、daily failure notice | 降级为对话偏好或 automation/thread 上下文 |
| `SchedulerCapability` | cron、automation、scheduled task、heartbeat | 每日推荐 | 有能力时先 `pending_schedule`，创建成功后 `enabled`；无能力时 `unsupported` |

平台适配提示：

- Hermes：优先 Web Search & Extract；没有专门搜索时可用 Browser Automation 打开搜索页。
- OpenClaw / 定制 OpenClaw：优先启用 `web_search` 或 browser tool；只有这些都不可用时，才考虑低风险 shell 读取公开网页/API。
- Claude Code：优先 WebSearch/WebFetch；Bash 只作为最后降级读取公开文本/JSON，避免 `curl | python`、`curl | sh`、`python -c` 处理远程输入。
- Codex：优先 web search / browser / automation；本地 helper 可用但不得替代原生搜索。
- 私有 Agent：满足能力契约即可，不需要工具同名。

## No-approval Runtime

运行时禁止：

- 用 shell 联网作为第一搜索路径
- 用 `curl` / `wget` 获取远程内容后直接执行或管道进解释器
- `python -c` / `python3 -c` 处理远程 stdin 或执行远程内容
- `git` / `gh` / `npm` / `npx` / `pip` / `uvx` 搜索、安装或下载
- `curl | python`、`curl | sh`、网络输出直接进入解释器或脚本
- daily 自动任务中任何会触发当前 Agent 权限审批的 fallback

运行时允许：

- Agent 原生搜索工具
- Agent 原生浏览器工具
- 已安装且免审批的搜索/浏览 MCP
- 当搜索和浏览都不可用时，用 shell 作为最后降级读取公开网页/API，前提是只保存或展示原始 HTML/JSON/text，不安装依赖，不执行远程内容，不把网络输出直接管道进解释器；如果会弹审批，manual 先说明原因并等待用户确认，daily 进入失败提醒
- 本地确定性 helper，前提是只读写本地 JSON，不联网、不安装依赖、不调用外部命令，且当前 Agent 不会弹审批
- Agent 对可见网页结果的自然语言解析和排序

如果本地 helper 会触发审批，跳过 helper，按本文规则直接过滤和推荐。

## Persistent State

用户状态不得只保存在 skill 安装目录内。Hermes 等平台重新安装 skill 时可能先删除目录再 clone 仓库，如果状态放在 `data/state.json`，`daily_rec_status` 会被重置成 `unset`，已有定时任务随后会静默退出。

状态读取优先级：

1. 平台原生 `StateCapability` / memory / skill state。
2. 外部持久 JSON：默认 `~/.hermes/state/skill-recommender/state.json`，或 `SKILL_RECOMMENDER_STATE_DIR/state.json`。
3. 仓库内 `data/state.json` 只作为模板和开发样例，不作为用户持久状态。

历史记录同理：默认写到 `~/.hermes/state/skill-recommender/history.json`，仓库内 `data/history.json` 只作为模板。安装、更新或重新 clone skill 时，不应覆盖外部状态。

如果发现旧版本曾把状态写在仓库内 `data/state.json`，且外部状态不存在，可以迁移一次；迁移后继续读写外部路径。

`timezone: null` 表示未配置用户时区。此时本地 helper 应按当前 scheduler/Agent 运行环境的本地时区判断“今天”，而不是固定 UTC 或固定 Asia/Shanghai。`push_time_local` 表示用户希望的本地推送时间；如果平台支持明确时区，优先使用平台/用户时区，否则按 scheduler 本地时区解释。

## 推荐信号模型

Skill Recommender 不是“按已安装 skill 猜偏好”的系统。执行推荐时按以下信号判断：

1. **当前任务**：用户此刻想完成什么，是否有明确问题、文件类型、业务目标或工具缺口。
2. **长期场景/领域**：用户近期反复出现的行业、工作流或生活场景，如教育学习、内容创作、投资研究、文档处理、产品设计、运营、法务合规、个人事务等。
3. **能力缺口**：当前 Agent 缺少搜索、浏览、文件处理、表格、日历、邮件、知识库、自动化、媒体处理等哪类能力。
4. **多源候选竞争**：同一需求至少尝试从多个平台找候选，再比较可信度、安装可行性、维护状态和实际覆盖范围。
5. **网络趋势**：近期在多个来源出现、更新活跃、星标/下载增长、社区讨论增多或热门榜上升的能力可以加分。
6. **种草价值**：daily 推荐要判断用户看到后会不会想试一下；痛点要具体，爽点要清楚，不能只说“提升效率”。
7. **生产力跃迁**：候选最好能让用户少做重复工作、打开新工作流、降低工具切换成本或显著提高质量。
8. **已安装 skill**：只用于判断重复、已有覆盖、互补关系和最终小权重 tie-breaker。

manual / 当前任务型推荐权重：

- 当前任务匹配度：30%
- 能力缺口匹配度：20%
- 长期场景/领域匹配度：15%
- 生产力跃迁价值：15%
- 多源可信度和安全：10%
- 网络趋势热度：5%
- 已安装 skill 互补性：5%

daily / 精选探索推荐权重：

- 用户可能会想试：25%
- 网络热度/近期流行：20%
- 日常生活或内容场景关联：15%
- 当前能力缺口：15%
- 生产力/省事价值：10%
- 多源可信度和安全：10%
- 新鲜度/多样性：5%

长期场景记忆可以来自状态、当前会话、用户明确偏好、workspace 或近期推荐反馈；没有可靠状态时，只在本轮基于可见证据推断。不要因为用户乱装过某类 skill 就把它当成长期偏好。

`scenario_memory` 和 `daily_rotation` 是 Agent 运行时维护的可选状态，不要求本地 helper 自动推理或写入。当前 Agent 有 `StateCapability` 时可以更新这些字段；没有状态能力或字段为空时，直接按当前可见证据临时判断，不要因为字段为空而阻断推荐。

Daily 推荐不是审计报告，而是“今天发现一个值得试的新能力”。在安全和真实证据满足后，优先挑能直击具体痛点、热门、有趣、生活化或内容场景强的候选；不要每天都推严肃工作流工具。

## AGENT POST-INSTALL HOOK

安装或更新本 skill 后，Agent 应执行一次轻量 onboarding，用来尽早开启每日推荐，但不能静默创建定时任务。

1. 读取平台原生 skill state 或外部持久状态；不要把仓库内 `data/state.json` 当作用户状态。
2. `daily_rec_status == "enabled"`：不询问。
3. `daily_rec_status == "disabled"`：不询问，除非用户主动要求开启。
4. `daily_rec_status == "prompted"`：不重复询问，除非用户主动要求开启。
5. `daily_rec_status == "pending_schedule"`：说明用户已同意但 automation 还未确认创建成功；尝试继续创建 automation，不要当成已开启。
6. `daily_rec_status == "unsupported"`：不重复询问，除非用户主动要求开启且当前 Agent 已有 `SchedulerCapability`。
7. `daily_rec_status == "unset"`：用 `StateCapability` 或免审批 helper 标记为 `prompted`，然后只问一个问题：
   「要不要开启每日推荐？我会每天早上 10:00 给你推荐一个适合你的实用 AI 自动化能力。回复「开启」我就帮你设置，回复「不用」就保持手动推荐。」
8. 提问后立即停止输出，等待用户回复。不要同一条消息里推荐 skill、做基础能力诊断或询问其他授权。
9. 用户回复「开启」：先设为 `pending_schedule` 并创建 `skill-recommender-daily` automation；只有 automation 创建成功后才设为 `enabled`。
10. automation 创建失败：不要保持 `enabled`，状态回到 `prompted` 并记录失败原因。
11. 用户回复「不用」或拒绝：状态设为 `disabled`。
12. 当前 Agent 没有 `SchedulerCapability`：说明无法自动创建每日任务，状态设为 `unsupported`。

可使用免审批 helper：

```bash
python3 scripts/feedback.py prompt-daily --source post_install
python3 scripts/feedback.py enable-daily
python3 scripts/feedback.py confirm-daily-enabled
python3 scripts/feedback.py fail-daily-schedule --reason "schedule_create_failed"
python3 scripts/feedback.py disable-daily
python3 scripts/feedback.py unsupported-daily
```

这些命令只在不会触发审批时使用；否则使用平台原生状态能力或对话状态。
默认 helper 会把状态写到外部持久目录，而不是 skill 仓库内的 `data/` 模板。

## Manual 推荐流程

触发条件：用户说「推荐个 skill」「有什么新工具」「帮我找个能...的 skill」「最近有什么好用的工具」等。

1. 收集上下文信号：用户当前请求、长期场景/领域、能力缺口、workspace、可用工具、已安装 skill、候选来源和趋势证据。
2. 诊断当前 Agent 是否已有能力能覆盖需求；已有能力时优先告诉用户怎么用，不重复推荐安装。
3. 检查 `SearchCapability` / `BrowserCapability`。
4. 有搜索能力：按 multi-recall 搜索候选，至少尝试当前任务、长期场景、能力缺口、趋势四类查询。
5. 无搜索但有浏览器能力：打开 Brave Search 网页版或 DuckDuckGo 搜索页，按同样的 multi-recall 查询读取结果。
6. 搜索/浏览能力都没有：可把 shell 作为最后降级路径读取公开网页/API，但只允许“获取数据供 Agent 审阅”，不得 `curl | python/sh`、不得执行远程内容、不得安装依赖。若会弹审批，先说明“当前没有原生搜索/浏览能力，需要用命令行读取公开搜索结果”，由用户决定是否继续；用户不授权时，建议启用当前 Agent 的原生搜索或浏览能力。
7. 合并 15-25 个候选，跨平台去重，过滤安全和已有覆盖，再按 manual 权重排序。
8. 如有 `StateCapability` 或免审批 helper，记录 `shown`；否则不强制写文件。
9. 执行 Post-Recommend Update Check；如发现新版且本轮没有其他授权问题，在推荐末尾询问是否更新。

## Daily 推荐流程

触发条件：`skill-recommender-daily` automation。

1. `daily_rec_status != "enabled"`：静默退出。
2. 检查 `SearchCapability` / `BrowserCapability`。
3. 选择今日探索主题：实用增强、热门发现、有趣尝鲜三类轮换；无状态时优先热门发现，其次长期场景。
4. 有搜索能力：按 Task Recall、Scenario Recall、Gap Recall、Hot Recall、Delight Recall、Utility Recall、Diversity Recall 搜索候选。
5. 无搜索但有浏览器能力：打开 Brave Search 网页版或 DuckDuckGo 搜索页，按同样召回路径读取结果。
6. 搜索/浏览能力都没有：只有在 shell 读取公开网页/API 不触发审批、且不会执行远程内容时，才可作为最后降级路径；否则进入 Daily Failure Notice，不在自动任务里等待用户授权。
7. 只允许 low 风险候选；medium/high 不推。
8. 候选必须有明确价值：种草感、日常场景价值、能力补齐、生产力/省事价值至少满足其一；只有“热门”但没有具体使用场景、爽点或可信来源时不推。
9. 输出 1 个推荐；如有状态能力，记录 `shown`、去重信息和今日探索主题。
10. 执行 Post-Recommend Update Check；如发现新版且本轮没有其他授权问题，在推荐末尾询问是否更新。
11. 没有合格候选时静默，不硬推，也不单独为了更新提醒发消息。

Cron/automation prompt 应表达以下约束。`feedback.py` 只返回短 prompt；完整运行规则以本节为准，避免双处维护。

```text
Load the skill-recommender skill and run the Daily 推荐流程 defined in SKILL.md. Use persistent state outside the skill install directory.
```

## Daily Failure Notice

当 daily 已开启，但运行时没有无审批搜索/浏览能力时，不要每天静默失败，也不要每天骚扰用户。

状态字段：

```json
{
  "daily_failure_notice_status": "unset",
  "daily_failure_notice_reason": null,
  "daily_failure_notice_last_shown_at": null
}
```

状态含义：

- `unset`：从未提醒过
- `shown`：已经提醒过一次，用户未明确关闭
- `dismissed`：用户选择不再提醒
- `resolved`：后来检测到搜索/浏览能力恢复

行为：

1. `unset` 或 `resolved`：发送一次失败提醒，并尽量标记为 `shown`。
2. `shown`：默认静默退出，不每天重复提醒。
3. `dismissed`：静默退出，除非用户主动恢复提醒。

提醒文案必须包含：

- 今日技能推荐失败
- 原因：当前 Agent 没有可用的无审批联网搜索或浏览能力
- 建议：启用当前 Agent 的原生搜索/浏览能力
- 选择：「帮我配置」「稍后再说」「不再提醒」

平台化建议：

- Hermes：Web Search & Extract 或 Browser Automation
- OpenClaw：`web_search` 或 browser tool
- Claude Code：WebSearch/WebFetch
- Codex：web search / browser / automation
- 私有 Agent：启用等价的 search/browser capability

不要默认要求用户申请 API key。不要默认推荐 Brave Search MCP、Tavily、Exa、Perplexity；这些可作为用户追问时的增强选项。

## Post-Recommend Update Check

Skill Recommender 可以在推荐完成后检查自身是否有新版。更新检查是附加提醒，不是启动门槛。

触发时机：

1. manual：推荐内容输出并记录 `shown` 后、等待用户反馈前。
2. daily：今日推荐内容输出后，同一条消息末尾。
3. 没有合格推荐时：静默，不单独发送更新提醒。

检查规则：

- 只使用 Agent 原生搜索、WebFetch、浏览器、GitHub connector 或等价无审批能力读取远端 `VERSION.json`。
- 本地版本从仓库根目录 `VERSION.json` 读取；如果没有本地版本文件，视为未发布本地版本，但不得阻断推荐。
- 不使用 shell、`curl`、`wget`、`git ls-remote`、`gh`、`python -c` 或外部 CLI 检查版本。
- 按 SemVer 比较版本；只有远端版本严格大于本地版本时才继续提醒。远端版本小于或等于本地版本、版本字段缺失、或版本格式无法解析时，静默跳过。
- 没有无审批联网/读取能力时，静默跳过。
- 同一个远端版本最多提醒一次，除非用户主动询问更新。
- 如果本轮已经包含安装授权、daily 开启或失败提醒配置，不追加更新问题。

版本规则：

- 仓库正式发布版本从 `1.0.0` 开始。
- PRD 迭代号不是发布版本号。
- 不要把 `version` 放入 `SKILL.md` frontmatter；使用 `VERSION.json`。

更新询问文案：

```text
另外，Skill Recommender 有新版可用。要不要更新到最新版本？
回复「更新」我就帮你处理，回复「暂不更新」这次先不管。
```

用户回复「更新」后：

1. 优先使用当前 Agent 的原生 skill update / installer 能力。
2. 如果当前 skill 目录是 git repo，且 `git pull` 或等价操作不触发审批，可以更新。
3. 如果更新需要权限审批，必须先说明原因并等待用户确认。
4. 如果不是 git repo 且没有平台更新能力，提供重新安装或手动更新路径。

## 候选收集

优先来源：

1. ClawHub
2. MCP Market
3. Smithery
4. Glama
5. GitHub

搜索方式：

- 有 `SearchCapability`：用原生搜索工具搜 `site:clawhub.ai skills trending`、`site:mcpmarket.com skills`、`site:smithery.ai new skills`、`site:glama.ai mcp servers`、`mcp server skill trending`。
- 只有 `BrowserCapability`：打开 Brave Search 网页版或 DuckDuckGo，读取搜索结果和详情页。
- 搜索/浏览能力都没有时，manual 可在用户确认后用低风险 shell 读取公开网页/API；daily 只能在无需审批时使用。命令行结果应先保存为 JSON/HTML/text 再由 Agent 审阅，不要把网络输出直接传给解释器或脚本。
- DuckDuckGo 可能对 headless 浏览器返回 CAPTCHA 或空结果（标准版和 HTML 版均可能触发）。备选：Yahoo Search (`search.yahoo.com/search?p=...`) 实测对 headless 浏览器友好，可作为第一降级路径。
- X/Twitter 不作为 daily 默认来源；manual 探索可用但至少 medium 风险。
- 不用固定候选池兜底；`data/sample_candidates.json` 只用于测试。

multi-recall 查询路径：

1. **Task Recall**：围绕用户当前请求搜索，例如“PDF summarize agent skill”“calendar automation skill”。
2. **Scenario Recall**：围绕长期场景搜索，例如“education AI skill”“content creation agent skill”。
3. **Gap Recall**：围绕缺失能力搜索，例如“browser automation skill”“spreadsheet agent skill”。
4. **Hot Recall**：搜索热门榜、下载榜、近期 star 增长、社区讨论，例如“popular AI agent skills”“trending MCP server”“new agent skill this week”。
5. **Delight Recall**：搜索好玩或强种草能力，例如“fun AI tools agent skill”“writing humanizer skill”“content creation agent skill”。
6. **Utility Recall**：搜索日常高频场景，例如股票分析、旅行规划、读书整理、健身、购物比价、邮件润色。
7. **Diversity Recall**：daily 额外找一个非重复的大众场景，避免长期只推同类工作工具。

每条路径最多保留 5 个候选；总候选建议 15-25 个。候选必须来自当前可见网页或搜索结果，不要凭记忆编造。

候选归一化字段：

```json
{
  "skill_id": "source:name-lower",
  "name": "Skill Name",
  "url": "https://...",
  "source_code_url": "GitHub URL",
  "description": "一句话描述",
  "categories": ["documents", "web-research"],
  "source": "clawhub|mcpmarket|smithery|glama|github|x",
  "updated_at": "ISO 8601",
  "popularity": {"downloads": 0, "stars": 0},
  "required_toolsets": ["browser"],
  "complexity": "lightweight|framework|platform",
  "trend": {
    "source_count": 1,
    "recent_mentions": 0,
    "updated_recently": true,
    "trend_reason": "近期在多个来源出现或增长较快"
  },
  "has_install_docs": true,
  "has_security_disclosure": false,
  "risk_level": "low|medium|high"
}
```

## 过滤与安全

Agent 运行时按以下规则过滤。可用免审批 helper 时可以用 `scripts/candidate_filter.py` 和 `scripts/security.py` 增强，但不要依赖它们。

过滤规则：

- 去重：`skill_id` 和归一化名称重复时保留可信度最高来源。
- 已安装过滤：已安装 skill 不再推荐。
- 冷却：14 天内拒绝过的跳过；30 天内展示过的跳过。
- 质量：描述太短、来源不明、没有详情页或没有安装说明的降权或过滤。
- 明确价值：没有种草感、日常场景价值、能力补齐或生产力/省事价值的候选降权；daily 直接过滤。
- 趋势约束：网络热门只能加分；如果任务不匹配、风险过高或安装不可行，不得推荐。
- daily 限额：automation 本身应每天最多运行一次；如有状态能力，再按本地日期去重。

安全规则：

- low：manual/daily 都可推荐。
- medium：manual 可推荐但必须标注风险；daily 不推荐。
- high：永不推荐。
- 来源未知、X/Twitter、元数据不足至少 medium。
- 命中危险模式、请求敏感凭据、要求全盘文件/浏览器 cookie/SSH/环境变量权限时，至少 medium；明显危险时 high。
- 候选已有风险标记时只升不降。

## 排序策略

先过滤，再排序。排序时不要让“用户已安装过某类 skill”主导结果。

manual / 当前任务型推荐：

1. 当前任务匹配度：候选是否直接解决用户此刻的需求。
2. 能力缺口匹配度：候选是否补齐当前 Agent 缺的关键能力。
3. 长期场景/领域匹配度：候选是否贴合用户反复出现的行业或生活/工作场景。
4. 生产力跃迁价值：候选是否显著减少重复步骤、打开新流程或提升输出质量。
5. 多源可信度和安全：来源是否可靠、是否有安装说明、是否低风险。
6. 网络趋势热度：近期是否被多个来源提到或维护活跃。
7. 已安装 skill 互补性：只作为小权重 tie-breaker，不可覆盖前六项。
   `data/complement_pairs.json` 只是大众场景互补参考，不是偏好来源或排序主因。

daily / 精选探索推荐：

1. 用户可能会想试：痛点是否具体，爽点是否一眼能懂。
2. 网络热度/近期流行
3. 日常生活或内容场景关联
4. 当前能力缺口
5. 生产力/省事价值
6. 新鲜度/多样性
7. 多源可信度和安全
8. 已安装 skill 只用于去重、已有覆盖和轻量互补，不参与主排序。

daily 推荐按“实用增强 / 热门发现 / 有趣尝鲜”轮换，不要连续多天只推荐开发、运维、文档、效率类工具。可以推荐大众会想试的内容创作、投资观察、个人管理、生活自动化、AI 文风处理、媒体处理等能力。

manual / daily 共同底线：

1. 安全、来源和安装可行性
2. 真实可见证据
3. 不重复推荐已安装 skill
4. 不因为“好玩”推荐高风险或无安装说明的候选

## 输出格式

推荐输出不要用 markdown 表格。manual 可以解释更完整；daily 要短、像种草，不要像审计报告。

Daily 默认结构：

```text
📡 每日精选推荐 · <日期>
🎯 今日推荐：<skill name> — <一句话定位>
这个 skill 专治一个很常见的问题：<用一句人话说痛点>
它能做什么：
• <亮点 1>
• <亮点 2>
• <亮点 3>
为什么值得装：<结合用户场景/热门趋势/实际爽点，用 2-3 句话讲清楚>
来源：<URL>
安全状态：<低风险来源；medium 只在 manual 展示并说明风险>
需要我帮你装上吗？回复「安装」即可。
<可选：如果发现 Skill Recommender 有新版，且本轮没有其他授权问题，在这里追加更新询问>
```

Manual 默认结构：`推荐给你：<skill name> — <定位>`，再用短段落说明它解决的具体痛点、3 个以内亮点、为什么适合当前任务/场景、来源、已安装状态、安全状态，最后询问是否安装。

规则：

- 推荐理由必须说明可见证据；不声称使用不可见历史、工具调用统计或未读取数据。
- 长期场景必须来自当前会话、可见状态、workspace 或明确反馈。
- 趋势证据写进“为什么值得装”；没有趋势数据就不要硬写。
- 安全状态默认一句话；medium 风险只在 manual 展开提醒，daily 不输出。
- 更新提醒只能出现在推荐后；无新版、无无审批检查能力或本轮已有其他授权问题时省略。
- 无合格候选时不硬推。

## 反馈与状态

优先用 `StateCapability` 记录状态。没有免审批状态能力时，反馈可以降级为对话偏好。

可记录的推荐事实包括：`shown`、`accepted`、`rejected`、daily 授权状态、daily 失败提醒状态、更新提醒状态、最近展示类别、可见场景线索和今日探索主题。场景线索只保存可解释事实，例如“最近多次请求文档处理/学习资料整理”，不要保存无法追溯的复杂画像。

`scenario_memory` 和 `daily_rotation` 的维护责任在 Agent 或平台状态能力，不在 `feedback.py`。本地 helper 只处理确定性反馈和授权状态；如果未来确认某个平台能免审批写状态，再增加专门 helper 命令。

可选 helper：

```bash
python3 scripts/feedback.py shown --skill-id "..." --skill-name "..." --categories "..." --skill-url "..."
python3 scripts/feedback.py accept --skill-id "..." --categories "..."
python3 scripts/feedback.py reject --skill-id "..." --categories "..."
python3 scripts/feedback.py prompt-daily --source manual
python3 scripts/feedback.py enable-daily
python3 scripts/feedback.py confirm-daily-enabled
python3 scripts/feedback.py fail-daily-schedule --reason "schedule_create_failed"
python3 scripts/feedback.py disable-daily
python3 scripts/feedback.py unsupported-daily
```

只在不触发审批时使用这些 helper。若会触发审批，不要为了记录状态打断用户。

每日推荐授权规则：

1. 只有 `daily_rec_status == "enabled"` 才运行 daily。
2. `prompted`、`pending_schedule`、`enabled`、`disabled`、`unsupported` 状态下不自动重复询问 daily。
3. manual 推荐后只有 `daily_rec_status == "unset"` 且当前回复没有其他授权问题时，才可以补问 daily。
4. 询问 daily 前先标记为 `prompted`，防止 post-install 和 manual 重复问。
5. 用户回复「开启」：先调用 `enable-daily` 获取 cron 配置并进入 `pending_schedule`。
6. automation 创建成功后：调用 `confirm-daily-enabled`，状态才设为 `enabled`。
7. automation 创建失败后：调用 `fail-daily-schedule`，状态回到 `prompted` 并记录失败原因。
8. 用户回复「不用」：状态设为 `disabled`。
9. 当前 Agent 不支持定时任务：状态设为 `unsupported`。

更新提醒状态规则：

1. `auto_update_status == "disabled"`：不主动检查或提醒更新，除非用户主动询问。
2. `auto_update_status == "unsupported"`：当前环境无法无审批检查更新，静默跳过。
3. `update_notice_status == "shown"` 或 `dismissed` 且 `last_seen_remote_version` 未变化：不重复提醒。
4. 发现新远端版本时，可将 `last_seen_remote_version` 更新为该版本，并将 `update_notice_status` 设为 `shown`。
5. 用户回复「暂不更新」或「不再提醒」：对当前远端版本设为 `dismissed`。
6. 用户回复「更新」：设为 `accepted`，再进入用户确认后的更新执行流程。

## 本地脚本

| 脚本 | 用途 | 类型 |
|------|------|------|
| `scripts/candidate_filter.py` | 去重 + 冷却 + 已安装过滤 | 可选 helper |
| `scripts/security.py` | 来源可信度 + 元数据 + 模式扫描 | 可选 helper |
| `scripts/feedback.py` | 处理用户反馈和 daily 状态 | 可选 helper |
| `scripts/state_store.py` | 状态/历史 JSON 读写 | 可选 helper |

这些脚本不得联网、安装依赖或调用外部命令。如果当前 Agent 会为本地脚本弹审批，跳过脚本并按本文规则执行。
`scripts/feedback.py` 默认读写外部持久状态目录；`scripts/candidate_filter.py` 如需传入状态文件，应优先传外部状态路径。

## 常见踩坑

1. **弹出命令审批**：如果是原生搜索/浏览或本地 helper，跳过该路径；如果 manual 只有 shell 能联网，先说明原因再等用户授权。daily 不等待审批。
2. **只有 shell 能联网**：shell 只是最后降级，只能读取公开数据供 Agent 审阅；禁止 `curl | python/sh`、安装依赖或执行远程内容。
3. **daily 没有搜索能力**：最多提醒一次，并提供“不再提醒”。
4. **已安装权重过重**：把已安装 skill 降回去重、覆盖判断和 5% tie-breaker，不要当主偏好。
5. **热门但没价值**：趋势只能加分，不能替代任务匹配、安全和生产力跃迁。
6. **更新挡住推荐**：更新检查必须后置；没有推荐内容时不要单独推送更新提醒。
7. **重复提醒更新**：同一个远端版本最多提醒一次，除非用户主动询问。
8. **重装后 daily 不推**：检查是否误读仓库内 `data/state.json`；用户授权状态必须在外部持久状态或平台 state 中。
9. **推荐不准**：检查是否使用了真实可见证据，是否过度偏向 coding。
10. **cron 不执行**：检查 `daily_rec_status == "enabled"` 和当前 Agent 的 scheduler/automation 状态。
