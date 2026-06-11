# A_chatter 插件计划

中文名：进阶闲谈家

## 目标定位

A_chatter 是一个面向 MaiBot 的日程、提醒、联网检索与主动发言编排插件。插件不直接取代 Maisaka 的人格化表达，而是负责收集事实、选择时机、控制频率、执行权限判断，并将结构化上下文交给 Maisaka 生成符合人设的主动发言。

插件要解决的问题：

1. Bot 对日程、计划、定期提醒的支持弱。
2. Bot 主动发言缺少明确触发、频率控制和上下文组织。
3. Bot 信息检索能力弱，尤其是外界互联网信息。
4. 用户需要通过自然语言交互创建日程和主动发言任务。
5. 群聊和私聊需要不同权限、白名单和聊天密度配置。

## 已确认产品决策

1. 插件英文名和目录名为 `A_chatter`。
2. 中文显示名为“进阶闲谈家”。
3. 日程创建必须二次确认。
4. 二次确认流程必须使用 LLM generate 参与解析和确认文案生成。
5. 待确认草稿有效期为 5 分钟。
6. 联网检索使用 Tavily，API Key 写入插件配置。
7. 主动发言按执行形态分为两类：
   - 日程驱动：到点必须产生发言。
   - 自动发起：插件按目标和来源扫描，根据上下文、频率函数和 LLM 判断是否值得说。
8. “bot 想发言就发言”在纯插件方案中实现为 `auto_proactive` 的 `self_reflection` 来源，不是独立功能：
   - 当前 Maisaka 思考是由消息、timeout 或插件 proactive 唤醒的被动思考，不存在常驻自发产生候选意图的链路。
   - A_chatter 作为外部主动性层定期扫描目标聊天流，使用聊天历史、记忆、人设自省和可选联网信息生成候选意图。
   - 候选意图必须复用同一套频率密度函数、白名单、RBAC、安静时段和 LLM 判断流程。
   - 通过判断后才注入上下文并 `trigger_proactive` 唤醒 Maisaka。
9. 日程驱动的“必须发言”采用方案 A：
   - 优先触发 Maisaka 主动任务。
   - 插件观察一段时间内是否产生发言。
   - 如果没有发言，则由插件调用 LLM 生成兜底内容并通过 `send.text` 发送。
10. 允许跨聊天流创建或触发任务。
11. 权限由插件内置 RBAC 处理。
12. 支持群聊、个人白名单、群聊/个人频率配置，以及全局频率。
13. 频率不是简单上限，而是聊天密度控制参数。频率越高，主动发言密度越高。
14. 安静时段是可选功能。
15. 日程任务穿透安静时段时照常发，但会轻微影响发言风格：在提示词中说明当前处于安静时段，要求表达更轻、更短、更克制，但不得因此放弃日程发言。
16. 自动发起的 source 做混合策略，用户可以在配置中选择启用聊天历史、A_memorix 记忆、Tavily 检索、订阅主题、`self_reflection` 等发起来源。
17. `persona` 不是普通自动发起 source，而是所有主动发言都会使用的判断和生成上下文：
   - 普通自动发起不靠 persona 作为发起理由，persona 只影响 LLM 判断和表达方式。
   - `self_reflection` 是 persona-driven source，用人设主动生成“是否想说”的候选意图。
   - 最终触发 Maisaka 输出时，所有主动发言都必须带 persona context。

## 当前 MaiBot 能力依赖

本插件优先使用 SDK 能力，不直接导入主程序 `src.*`。

已确认可用能力：

1. `ctx.maisaka.append_context`
   - 底层能力：`maisaka.context.append`
   - 用途：向指定聊天流的 Maisaka 上下文写入插件事实、检索摘要、日程触发信息。

2. `ctx.maisaka.trigger_proactive`
   - 底层能力：`maisaka.proactive.trigger`
   - 用途：请求 Maisaka 基于指定聊天流主动处理一轮对话。

3. `ctx.message.get_recent`
   - 底层能力：`message.get_recent`
   - 用途：读取目标聊天流最近消息，辅助判断聊天氛围和生成上下文。

4. `ctx.message.build_readable`
   - 底层能力：`message.build_readable`
   - 用途：将消息列表转换成 LLM 友好的文本。

5. `ctx.knowledge.search`
   - 底层能力：`knowledge.search`
   - 用途：检索 A_memorix 长期记忆。

6. `ctx.llm.generate`
   - 底层能力：`llm.generate`
   - 用途：自然语言解析、任务草稿生成、确认文案、自动发起判断、检索摘要压缩、兜底发言。

7. `ctx.send.text`
   - 底层能力：`send.text`
   - 用途：硬提醒、确认交互、日程兜底发言。

8. `ctx.chat.get_stream_by_group_id` / `ctx.chat.get_stream_by_user_id`
   - 用途：跨聊天流创建任务时，将平台目标解析为真实 stream_id。

9. `@Tool` 插件工具组件
   - 用途：让 Maisaka 在自然语言聊天中主动调用 A_chatter 工具，完成任务草稿创建、确认、查询和管理。
   - 这条路径不要求用户输入 `/ac` 命令，适合“明天晚上提醒我交报告”“以后每天早上帮我看看新闻再找个话题聊”这类自然表达。

本地参考插件：

1. `plugins/mute_report_murmur`
   - 已经使用 `ctx.maisaka.append_context` 和 `ctx.maisaka.trigger_proactive` 实现事件驱动的小报告。
   - 本插件可以复用其“解析平台目标 -> 找 stream_id -> 注入上下文 -> 触发 Maisaka”的设计思路。

2. `plugins/hello_world_plugin`
   - 已经使用 `@Tool` 声明插件工具。
   - 本插件可以复用其 SDK 写法，但工具描述和参数 schema 必须更严格，方便 Maisaka planner 正确调用。

## 插件边界

插件负责：

1. 任务创建、确认、保存、查询、暂停、恢复、删除。
2. 权限和白名单判断。
3. 聊天密度计算。
4. 触发时机判断。
5. 聊天历史、长期记忆、联网检索等上下文收集。
6. Tavily 检索与结果摘要。
7. 将结构化事实写入 Maisaka 上下文。
8. 触发 Maisaka 主动任务。
9. 日程任务未发言时兜底发送。
10. 向 Maisaka 暴露工具组件，让 bot 能在自然语言对话中调用插件完成任务编排。

插件不负责：

1. 修改 Maisaka 内部规划器。
2. 修改 A_memorix 实现层。
3. 直接计算或写入主程序 session_id。
4. 直接改动根目录 `.gitignore`。
5. 不开发 WebUI。配置走插件配置模型和聊天命令交互。

## 入口设计

A_chatter 有三条入口：

1. 聊天命令入口
   - 用户显式输入 `/ac ...`。
   - 适合精确管理任务、查询状态、暂停恢复删除。

2. Maisaka 工具入口
   - 用户自然语言表达需求。
   - Maisaka planner 判断需要调用 A_chatter 工具。
   - 插件工具创建待确认草稿或执行查询、管理动作。
   - 适合“别让我忘了明晚交报告”“每天早上看一下 AI 新闻然后找个合适的话题聊”这类自然交互。

3. 后台调度入口
   - scheduler 扫描到期任务或自动发起机会。
   - 插件收集上下文并触发 Maisaka，或直接发送提醒。

三条入口共享同一套解析、RBAC、存储和执行服务，避免命令和工具出现两套行为。

## 插件目录建议

```text
plugins/A_chatter/
  _manifest.json
  plugin.py
  PLAN.md
  README.md
  docs/
    technical/
      TECHNICAL_DESIGN.md
      MESSAGE_FLOW.md
      CODE_STYLE.md
  a_chatter/
    __init__.py
    config.py
    models.py
    storage.py
    scheduler.py
    parser.py
    rbac.py
    frequency.py
    context_builder.py
    tavily_client.py
    proactive.py
    commands.py
    tools.py
    utils.py
  tests/
    test_frequency.py
    test_parser.py
    test_rbac.py
    test_storage.py
```

说明：

1. `plugin.py` 保持薄入口，注册命令、事件和生命周期。
2. 业务代码放入 `a_chatter/`，避免单文件过大。
3. 存储使用插件目录内 SQLite，例如 `data/a_chatter.sqlite3`。
4. 插件作为 `/plugins/A_chatter` 下独立仓库时，不修改根目录 `.gitignore`。

## 配置设计

配置模型按 UI 分组：

### plugin

```toml
[plugin]
enabled = true
config_version = "0.1.0"
```

### permissions

```toml
[permissions]
super_admins = ["qq:123456"]
default_allow_private_schedule = true
default_allow_group_schedule = false
allow_cross_stream_by_default = false
```

说明：

1. `super_admins` 拥有所有权限。
2. 普通用户默认可在自己的私聊创建个人任务。
3. 群聊任务默认更严格，需要群白名单、群管理员或显式授权。
4. 跨聊天流任务默认不允许，除非用户有 RBAC 权限。

### whitelist

```toml
[whitelist]
enabled = true
allowed_users = []
allowed_groups = []
allowed_private_users = []
```

说明：

1. `allowed_users` 格式：`platform:user_id`。
2. `allowed_groups` 格式：`platform:group_id`。
3. `allowed_private_users` 格式：`platform:user_id`，用于私聊主动发言目标。

### frequency

```toml
[frequency]
global_frequency = 1.0
base_interval_seconds = 3600
min_interval_seconds = 300
max_probability = 0.85
history_source_frequency = 0.8
memory_source_frequency = 0.8
web_source_frequency = 0.6
subscription_source_frequency = 0.7
self_reflection_source_frequency = 0.7
```

说明：

1. `global_frequency` 是全局聊天密度倍率。
2. `base_interval_seconds` 是频率为 1.0 时，自动发起累积概率的基础时间尺度。
3. `min_interval_seconds` 防止极高频率造成连续刷屏。
4. `max_probability` 防止概率无限接近 1。
5. 各 `source_frequency` 用于不同自动发起 source 的密度调节，和 `enabled_sources` 的 source 名称一一对应。

### targets

```toml
[[targets]]
target = "qq:group:123456"
enabled = true
frequency = 1.0
quiet_hours_enabled = false
quiet_hours = []
max_auto_runs_per_day = 6
max_schedule_fallbacks_per_day = 6
enabled_sources = ["history", "memory", "web", "subscription", "self_reflection"]
persona_context_enabled = true
```

说明：

1. `target` 使用平台目标格式，而不是内部 stream_id。
2. `frequency` 是目标聊天流密度倍率。
3. `enabled_sources` 控制该聊天流自动发言时允许使用的发起 source。
4. `persona_context_enabled` 控制主动发言判断和最终输出时是否注入插件侧 persona context；它不是发起 source。
5. `self_reflection` 表示由 A_chatter 定时触发、由 persona 驱动生成候选意图的自动发起 source，不表示 Maisaka 已具备常驻自发思考。

### tavily

```toml
[tavily]
enabled = true
api_key = ""
endpoint = "https://api.tavily.com/search"
max_results = 5
search_depth = "basic"
include_answer = true
include_raw_content = false
timeout_seconds = 20
```

说明：

1. Tavily API Key 只从插件配置中的 `api_key` 读取。
2. 如果 `api_key` 为空，联网检索源自动禁用，并在日志和命令查询中显示原因。

### confirmation

```toml
[confirmation]
pending_ttl_seconds = 300
max_pending_per_user = 3
```

说明：

1. 二次确认草稿有效期固定为 5 分钟，配置默认 300 秒。
2. 单用户待确认数量超限时，清理最旧草稿。

### proactive

```toml
[proactive]
maisaka_wait_seconds = 90
fallback_enabled = true
fallback_model_task = "utils"
fallback_max_tokens = 300
```

说明：

1. 日程驱动任务触发 Maisaka 后，等待 `maisaka_wait_seconds`。
2. 若未观察到新发言，执行兜底发言。
3. 兜底内容仍通过 LLM generate 生成，但应该短、明确、低风险。

## RBAC 设计

### 角色

1. `super_admin`
   - 拥有所有权限。

2. `target_admin`
   - 可以管理指定群聊或私聊目标的任务。
   - 可以给该目标创建日程、主动发言、订阅。

3. `trusted_user`
   - 可以创建个人任务。
   - 可以在白名单允许的目标创建任务。

4. `normal_user`
   - 只能创建当前私聊内和自己有关的个人任务。
   - 默认不能跨聊天流。

### 权限动作

1. `task.create.current`
2. `task.create.cross_stream`
3. `task.update`
4. `task.delete`
5. `task.pause`
6. `task.resume`
7. `task.view`
8. `config.view`
9. `config.update_runtime`

### 判断输入

每次命令处理时从 SDK kwargs 中读取：

1. `platform`
2. `user_id`
3. `stream_id`
4. `message`
5. 当前聊天类型和目标聊天流

注意：业务模块不自行调用 `SessionUtils.calculate_session_id`。跨聊天流时通过 `ctx.chat.get_stream_by_group_id` 或 `ctx.chat.get_stream_by_user_id` 解析真实 stream_id。

## 命令交互设计

命令前缀建议支持：

1. `/ac`
2. `/闲谈`
3. `/进阶闲谈`

### 创建任务

```text
/ac 新增 明天晚上八点提醒我交报告
/ac 新增 每周一上午九点在 123456 群里问大家本周计划
/ac 新增 每天早上八点根据科技新闻和群里最近聊天主动开个话题
```

流程：

1. 命令进入插件。
2. 插件收集当前用户、当前聊天流和原始文本。
3. 调用 `ctx.llm.generate` 解析为结构化草稿。
4. 插件校验草稿字段、权限、目标聊天流、时间表达式。
5. 插件生成确认文案。
6. 发送确认消息。
7. 用户 5 分钟内回复确认命令。
8. 插件保存任务。

### 确认任务

```text
/ac 确认
/ac 确认 <草稿ID>
/ac 取消
/ac 取消 <草稿ID>
```

如果用户没有提供草稿 ID：

1. 只有一个待确认草稿时默认使用它。
2. 多个待确认草稿时要求指定 ID。

### 查询任务

```text
/ac 列表
/ac 列表 当前
/ac 列表 qq:group:123456
/ac 查看 <任务ID>
```

展示字段：

1. 任务 ID
2. 类型
3. 目标聊天
4. 计划时间
5. 状态
6. 下次触发时间
7. 创建人

### 管理任务

```text
/ac 暂停 <任务ID>
/ac 恢复 <任务ID>
/ac 删除 <任务ID>
/ac 立即运行 <任务ID>
```

`立即运行` 需要较高权限，尤其是跨聊天流目标。

### 配置状态查询

```text
/ac 状态
/ac 权限
/ac 频率
/ac 检索状态
```

不建议通过聊天命令大量修改配置，避免权限和审计复杂化。聊天命令主要提供状态查询和任务管理，长期配置以插件配置文件为准。

## Maisaka 工具交互设计

### 工具定位

Maisaka 工具入口用于让 bot 在普通聊天中自然调用 A_chatter，而不是要求用户记住 `/ac` 命令。

示例：

```text
用户：明天晚上八点提醒我交报告
Maisaka：调用 a_chatter_create_task_draft
A_chatter：创建待确认草稿并返回确认摘要
Maisaka：把确认摘要转述给用户，询问是否确认
用户：确认
Maisaka：调用 a_chatter_confirm_task
A_chatter：保存任务并返回结果
Maisaka：自然回复用户任务已设置
```

### 工具列表

建议暴露这些 Tool：

1. `a_chatter_create_task_draft`
   - 从自然语言创建待确认任务草稿。
   - 只保存 pending confirmation，不直接创建正式任务。
   - 仍然使用 `ctx.llm.generate` 做结构化解析和确认摘要。

2. `a_chatter_confirm_task`
   - 确认最近或指定草稿。
   - 成功后写入正式任务。

3. `a_chatter_cancel_draft`
   - 取消最近或指定草稿。

4. `a_chatter_list_tasks`
   - 查询当前聊天流或指定目标的任务。

5. `a_chatter_manage_task`
   - 暂停、恢复、删除、立即运行指定任务。

6. `a_chatter_query_status`
   - 查询插件状态、权限状态、频率状态、Tavily 配置状态。

### 工具可见性

为了让自然语言链路足够顺滑，建议：

1. `a_chatter_create_task_draft` 设置为 `visibility="visible"`。
2. `a_chatter_confirm_task` 设置为 `visibility="visible"`。
3. 查询和管理类工具可以先保持默认 deferred，让 Maisaka 通过 `tool_search` 发现。

这样用户自然说“提醒我...”时，Maisaka 能直接看到创建和确认工具；较少使用的管理工具不会挤占 planner 工具窗口。

### 工具返回约定

工具返回 dict：

```json
{
  "success": true,
  "content": "已创建待确认草稿，请用户确认。",
  "draft_id": "draft_xxx",
  "requires_user_confirmation": true,
  "confirmation_expires_in_seconds": 300,
  "task_preview": {}
}
```

返回内容要给 Maisaka 使用，而不是直接面向用户的完整最终话术。Maisaka 负责自然转述。

### 二次确认约束

无论从命令入口还是 Maisaka 工具入口创建日程，都必须二次确认。

工具入口的确认方式：

1. 用户可以自然说“确认”“就这样”“取消”等。
2. Maisaka 应调用 `a_chatter_confirm_task` 或 `a_chatter_cancel_draft`。
3. 如果用户绕过 Maisaka 直接使用 `/ac 确认`，也可以确认同一份 pending draft。

### 权限与上下文

插件工具执行时需要读取 SDK 注入的上下文字段：

1. `stream_id` / `chat_id`
2. `platform`
3. `user_id`
4. `group_id`

这些字段用于：

1. 判断 actor 身份。
2. 确定默认目标聊天流。
3. 执行 RBAC。
4. 跨聊天流目标解析。

工具不得自行计算 session_id。

## LLM 解析草稿格式

LLM 解析结果必须是 JSON。建议结构：

```json
{
  "task_type": "reminder|schedule_proactive|auto_proactive|research_digest",
  "title": "交报告提醒",
  "target": {
    "scope": "current|explicit",
    "platform": "qq",
    "chat_type": "group|private",
    "target_id": "123456",
    "stream_id": ""
  },
  "schedule": {
    "kind": "once|cron|interval",
    "timezone": "Asia/Shanghai",
    "run_at": "2026-06-11T20:00:00+08:00",
    "cron": "",
    "interval_seconds": 0
  },
  "content": {
    "user_intent": "提醒我交报告",
    "must_say": true,
    "requires_web": false,
    "web_query": "",
    "memory_query": "",
    "style_hint": ""
  },
  "safety": {
    "needs_cross_stream_permission": false,
    "confidence": 0.91,
    "ambiguities": []
  }
}
```

校验规则：

1. `task_type` 必须是允许值。
2. `schedule.kind` 必须可执行。
3. `target.scope = explicit` 时必须解析真实目标。
4. `confidence < 0.7` 或 `ambiguities` 非空时，不能直接生成确认，需要追问用户。
5. 所有时间转换为带时区的绝对时间。

## 任务类型

### reminder

硬提醒任务。

执行方式：

1. 到点。
2. 构造提醒文本。
3. `ctx.send.text` 直接发送。

适用场景：

1. “提醒我交报告。”
2. “明天 8 点叫我起床。”

### schedule_proactive

日程驱动的主动发言任务。

执行方式：

1. 到点。
2. 收集上下文。
3. 注入 Maisaka 上下文。
4. 触发 Maisaka 主动任务。
5. 等待 `proactive.maisaka_wait_seconds`。
6. 如果没有观察到发言，使用 LLM generate 生成兜底文本并 `send.text`。

必须发言：

1. 这个任务不通过概率判断是否应该说。
2. 安静时段只轻微影响风格。
3. 白名单、权限和目标可用性仍然必须满足。

### auto_proactive

自动发起任务。

`auto_proactive` 是唯一的自动主动发起执行链路。普通自动话题、联网热点、记忆关心、订阅主题和 `self_reflection` 都只是不同 `source`，不能实现成多套调度或多套触发逻辑。

其中 `self_reflection` 用来覆盖“bot 想发言就发言”的体验。它不是 Maisaka 原生常驻思考给出的候选意图，而是 A_chatter 在扫描目标聊天流时，用聊天历史、记忆、人设自省和可选联网信息生成候选意图，再通过统一频率密度流程决定是否唤醒 Maisaka。

`persona` 不属于普通自动发起 source。普通 source 的发起理由来自 history、memory、web、subscription 等明确锚点；persona 只参与判断“该不该说”和“怎么说”。只有 `self_reflection` 把 persona 作为候选意图的驱动来源。

执行方式：

1. 周期性扫描目标聊天流。
2. 根据频率函数计算候选概率。
3. 如果候选概率命中，收集轻量聊天历史、记忆和可选联网信息。
4. 调用 LLM 判断当前是否存在值得说的意图。
5. 将 `intent_score` 带回同一套频率密度函数做最终放行判断。
6. 如果放行，构建完整上下文并触发 Maisaka。
7. 如果不值得说或未放行，只记录一次跳过原因。

### research_digest

联网摘要任务。

执行方式：

1. 到点。
2. 使用 Tavily 检索。
3. 去重和摘要压缩。
4. 根据任务配置选择：
   - 直接发摘要。
   - 注入 Maisaka 后人格化表达。
   - 作为 auto_proactive 的上下文来源。

## 频率函数设计

频率用于控制聊天密度，不是简单上限。

建议公式：

```text
effective_frequency = global_frequency * target_frequency * source_frequency * quiet_factor
expected_interval = base_interval_seconds / max(effective_frequency, epsilon)
raw_probability = 1 - exp(-elapsed_seconds / expected_interval)
trigger_probability = min(raw_probability, max_probability)
final_probability = trigger_probability * intent_score
```

硬间隔：

```text
if elapsed_seconds < min_interval_seconds:
    final_probability = 0
```

参数含义：

1. `global_frequency`
   - 全局密度倍率。
   - 例如 0.5 表示整体更少主动发起，2.0 表示更活跃。

2. `target_frequency`
   - 群聊或私聊目标密度倍率。

3. `source_frequency`
   - 不同来源的密度倍率。
   - 例如联网热点比历史延续更谨慎，`self_reflection` 可以比明确锚点来源更克制。

4. `quiet_factor`
   - 安静时段因子。
   - 对自动发起可以设置为 0 或低值。
   - 对日程驱动必须说任务只影响风格，不进入是否触发判断。

5. `elapsed_seconds`
   - 距离该目标上次主动发言的时间。

6. `intent_score`
   - LLM 对“现在是否值得说”的评分，范围 0 到 1。

7. `max_probability`
   - 概率上限，避免长时间沉默后必然刷屏。

8. `min_interval_seconds`
   - 同一目标两次自动主动发起之间的硬间隔。
   - 该值优先于概率计算，用于防止高频配置下连续触发。

特殊规则：

1. `effective_frequency <= 0` 表示该目标或来源禁用自动主动发起。
2. `schedule_proactive` 不用概率决定是否说。
3. `reminder` 不用概率。
4. 自动发起即使命中概率，也必须经过 LLM 判断。
5. `elapsed_seconds < min_interval_seconds` 时直接跳过自动发起。

## 安静时段设计

安静时段是可选功能。

每个目标可配置：

```toml
quiet_hours_enabled = true
quiet_hours = ["00:00-08:00"]
quiet_mode = "style_only|reduce|block_auto"
```

建议语义：

1. `style_only`
   - 不阻止发言，只在提示词中说明当前是安静时段。

2. `reduce`
   - 自动发起降频，例如 `quiet_factor = 0.2`。
   - 日程任务仍照常发。

3. `block_auto`
   - 自动发起完全阻止。
   - 日程任务仍照常发。

日程穿透安静时段的提示词片段：

```text
当前处于该聊天流配置的安静时段。本次是日程驱动任务，仍然需要发言。
请只让安静时段影响表达风格：更轻、更短、更克制，不要因此放弃发言。
```

## 上下文注入策略

上下文构造由 `context_builder.py` 负责。

### history

来源：`ctx.message.get_recent` + `ctx.message.build_readable`

用途：

1. 判断当前聊天氛围。
2. 避免突兀插话。
3. 找到可以自然衔接的话题。

配置：

```toml
history_limit = 30
history_hours = 12
```

### memory

来源：`ctx.knowledge.search`

用途：

1. 查询与任务主题、当前聊天流、用户有关的长期记忆。
2. 给 Maisaka 提供“这个群/这个人以前聊过什么”的材料。

注意：

1. 插件只通过 SDK 能力检索，不直接读取 A_memorix 存储。
2. 不自行计算 session_id。

### web

来源：Tavily。

用途：

1. 新闻、资料、外界状态。
2. 订阅主题。
3. 与聊天历史或记忆结合的外界信息补充。

流程：

1. 根据任务配置生成 Tavily query。
2. 调用 Tavily。
3. 去重 URL。
4. 截断过长内容。
5. 调用 LLM 生成事实包。
6. 将事实包注入 Maisaka。

### subscription

来源：用户配置或任务保存的订阅主题。

用途：

1. 按固定主题生成主动发起候选，例如科技新闻、天气、赛事、项目状态。
2. 给 `web` source 提供查询主题，或作为无联网时的本地主题锚点。
3. 与 history、memory、persona context 结合，判断当前是否适合把订阅主题带入聊天。

注意：

1. `subscription` 是普通 source，必须有明确订阅主题作为发起理由。
2. 如果只是人设上想开口，但没有订阅主题锚点，应归入 `self_reflection`。
3. 订阅主题的创建和管理仍走任务/RBAC/确认体系。

### persona_context

性质：所有主动发言都会使用的判断和生成上下文，不是普通自动发起 source。

用途：

1. 普通自动发起：影响 LLM 判断“该不该说”和表达风格，但不作为发起理由。
2. `self_reflection`：作为 persona-driven source 的核心材料，用来生成“是否想说”的候选意图。
3. 最终输出：所有 `schedule_proactive` 和 `auto_proactive` 都必须注入 persona context。
4. 不直接读取主程序人设文件，不重复主程序人设，只补充任务意图和表达边界。

### self_reflection

来源：A_chatter 的周期性扫描和 LLM 判断。

用途：

1. 实现“bot 想发言就发言”的纯插件版本。
2. 在 Maisaka 没有常驻自发思考的前提下，由插件基于 persona context 生成“是否有想说的话”的候选意图。
3. 该来源仍然必须经过白名单、RBAC、频率密度、安静时段和 LLM 判断。
4. 该来源不创建持久日程任务，只记录 run/audit。

## Tavily 检索设计

### 请求

默认 endpoint：

```text
https://api.tavily.com/search
```

请求字段建议：

```json
{
  "api_key": "...",
  "query": "...",
  "search_depth": "basic",
  "include_answer": true,
  "include_raw_content": false,
  "max_results": 5
}
```

### 响应归一化

统一成：

```json
{
  "title": "标题",
  "url": "https://example.com",
  "snippet": "摘要",
  "content": "正文或 raw_content",
  "published_at": "",
  "source": "tavily"
}
```

### 摘要压缩

压缩提示词目标：

1. 提取 3 到 7 条事实。
2. 保留来源 URL。
3. 标注不确定信息。
4. 不生成最终发言。
5. 不夸大检索结果。

输出示例：

```text
[联网检索事实包]
查询：...
1. ...
来源：...
2. ...
来源：...
```

## Maisaka 主动触发流程

### 自动主动发起统一流程

```text
调度器扫描
-> 选择 source: history / memory / web / subscription / self_reflection
-> 按来源计算初步频率概率
-> 概率命中
-> 收集该 source 需要的轻量上下文
-> 注入 persona context 辅助判断
-> LLM 判断是否存在值得说的意图
-> intent_score 参与最终频率密度放行
-> 收集完整上下文和 persona context
-> append_context
-> trigger_proactive
-> 记录 run
```

说明：

1. `self_reflection` 不拥有独立执行链路，只是 `source` 的一个取值。
2. 普通 source 的发起理由来自明确锚点，persona 只影响判断和表达。
3. `self_reflection` 由 persona 驱动候选意图，但不假设 Maisaka 自己在后台常驻思考。
4. 候选意图由 A_chatter 的 LLM 判断产生。
5. Maisaka 被唤醒后仍由自身 planner 决定最终表达。

### 日程驱动主动发言

```text
任务到点
-> 收集上下文
-> 如果安静时段，追加风格提示
-> append_context
-> trigger_proactive(priority="high")
-> 等待 Maisaka 发言
-> 若无发言，LLM 生成兜底文本
-> send.text
-> 记录 run
```

### 注入上下文结构

建议可见文本：

```text
[A_chatter 日程主动任务]
任务标题：...
任务类型：...
触发原因：...
目标聊天：...
是否必须发言：是
安静时段：是/否
用户原始意图：...

[最近聊天]
...

[长期记忆]
...

[联网事实]
...

[表达要求]
请结合当前聊天关系、长期记忆、联网事实和你的人设，自然发言。
```

### proactive intent

传给 `trigger_proactive` 的 `intent` 应短而明确：

```text
这是 A_chatter 的日程驱动主动任务：请围绕“...”在当前聊天流中自然发言。
本任务必须产生发言；如果当前是安静时段，只让它影响语气，不要放弃发言。
```

## 日程兜底发言设计

### 判断是否已发言

当前实现采用消息观察检测：

1. 触发前记录当前时间 `started_at`。
2. 等待 `maisaka_wait_seconds`。
3. 调用 `ctx.message.get_recent(target_stream_id, limit=20)`。
4. 查找 `timestamp > started_at` 且发送者是 bot 的消息。

潜在问题：

1. SDK 序列化消息中 bot 标识需要实测。
2. 如果无法可靠识别 bot 消息，可退化为检测目标聊天流是否出现新消息，并记录风险。
3. 若后续宿主提供发送回执或 proactive task 状态查询能力，可以替换为更精确的检测。

### 兜底文本要求

兜底只用于日程必须发言失败时。

要求：

1. 简短。
2. 明确。
3. 不伪装成完整 Maisaka 深度思考。
4. 不包含内部实现细节。
5. 如果是提醒任务，优先准确传达提醒。

兜底 prompt：

```text
你是 MaiBot 的发言兜底生成器。下面是一个已经到点且必须发言的日程任务。
请生成一条简短、自然、符合聊天语境的中文消息。
不要提到插件、调度器、兜底、系统失败等内部信息。
```

## 存储设计

使用插件自有 SQLite。

### tasks

字段：

1. `id`
2. `task_id`
3. `task_type`
4. `title`
5. `status`
6. `creator_platform`
7. `creator_user_id`
8. `source_stream_id`
9. `target_platform`
10. `target_chat_type`
11. `target_id`
12. `target_stream_id`
13. `schedule_kind`
14. `run_at`
15. `cron_expr`
16. `interval_seconds`
17. `timezone`
18. `must_say`
19. `requires_web`
20. `web_query`
21. `memory_query`
22. `enabled_sources_json`
23. `style_hint`
24. `created_at`
25. `updated_at`
26. `last_run_at`
27. `next_run_at`

### pending_confirmations

字段：

1. `draft_id`
2. `creator_platform`
3. `creator_user_id`
4. `source_stream_id`
5. `draft_json`
6. `expires_at`
7. `created_at`

### runs

字段：

1. `run_id`
2. `task_id`
3. `target_stream_id`
4. `triggered_at`
5. `status`
6. `maisaka_task_id`
7. `used_fallback`
8. `error`
9. `metadata_json`

### rbac_bindings

字段：

1. `id`
2. `subject`
3. `role`
4. `target`
5. `created_by`
6. `created_at`

其中：

1. `subject` 格式：`platform:user_id`。
2. `target` 格式：`global` 或 `platform:group:target_id` / `platform:private:target_id`。

### target_state

字段：

1. `target_stream_id`
2. `last_auto_run_at`
3. `last_schedule_run_at`
4. `last_message_seen_at`
5. `daily_auto_count`
6. `daily_fallback_count`
7. `date_key`

## 调度器设计

### 生命周期

1. `on_load`
   - 初始化存储。
   - 加载配置。
   - 启动后台 scheduler task。

2. `on_unload`
   - 设置停止事件。
   - 取消后台任务。
   - 等待任务退出。
   - 关闭 SQLite 连接。

3. `on_config_update`
   - 重新加载配置。
   - 刷新目标配置缓存。
   - 不删除已有任务。

### 主循环

```text
while not stopped:
    now = current time
    due_tasks = storage.list_due_tasks(now)
    for task in due_tasks:
        execute_task(task)
    scan_auto_targets_if_needed(now)
    sleep(next_tick_seconds)
```

建议：

1. tick 间隔 10 到 30 秒。
2. 单个任务执行要加锁，避免重复触发。
3. 失败任务记录 `runs`。
4. 周期任务执行后计算下一次时间。

## 自动发起判断

LLM 判断 prompt 输入：

1. 目标聊天信息。
2. 最近聊天历史。
3. 距离上次主动发言多久。
4. 频率函数产生的概率。
5. 启用的上下文来源。
6. 长期记忆摘要。
7. 可选联网事实包。
8. 当前自动发起 source，例如 `history`、`memory`、`web`、`subscription`、`self_reflection`。
9. persona context，用于影响判断和最终表达。

LLM 输出：

```json
{
  "should_speak": true,
  "intent_score": 0.73,
  "reason": "最近群聊在讨论周末计划，记忆中有人之前提到想看展，可以自然接话。",
  "intent_kind": "self_reflection",
  "topic": "周末看展计划",
  "web_query": "",
  "style_hint": "轻松、不要太长"
}
```

规则：

1. `should_speak = false` 时不触发 Maisaka。
2. `intent_score` 必须参与最终频率密度放行，不允许绕过频率控制。
3. 自动发起不兜底。
4. `self_reflection` 来源用于 persona-driven 的拟自发主动发言，但仍属于 `auto_proactive`。
5. 普通 source 不允许只靠 persona 凭空生成发起理由；若发起理由来自 persona 自省，应归入 `self_reflection`。

## 错误处理策略

1. 时间解析失败：追问用户，不保存草稿。
2. 权限不足：明确告诉用户缺少权限。
3. 目标聊天流不存在：提示需要先让 bot 与目标聊天流建立会话，或检查平台目标。
4. Tavily 未配置：联网源禁用，不影响非联网任务。
5. LLM 解析失败：提示用户换一种更明确的写法。
6. Maisaka 主动触发失败：
   - 日程任务：进入兜底。
   - 自动发起：记录失败，不补发。
7. SQLite 写入失败：让错误暴露到日志，并向用户提示任务保存失败，不做静默 fallback。

## 测试计划

### 单元测试

1. `frequency.py`
   - 频率越高，概率越高。
   - elapsed 越长，概率越高。
   - quiet factor 生效。
   - frequency 为 0 禁用自动发起。

2. `rbac.py`
   - super admin 权限。
   - target admin 权限。
   - 普通用户不能跨聊天流。
   - 白名单生效。

3. `parser.py`
   - LLM JSON 解析结果校验。
   - 模糊时间追问。
   - 低 confidence 不保存草稿。

4. `storage.py`
   - 任务增删改查。
   - due task 查询。
   - pending confirmation 过期清理。

5. `tavily_client.py`
   - 请求 payload。
   - 响应归一化。
   - API key 缺失时明确失败。

### 集成测试

1. 创建日程 -> LLM 草稿 -> 确认 -> 保存。
2. 日程到点 -> append_context -> trigger_proactive。
3. 日程触发后无发言 -> 兜底发送。
4. 自动发起 -> 频率函数 -> LLM 判断 -> 触发或跳过。
5. 跨聊天流创建 -> RBAC 校验 -> stream_id 解析。

## 实施阶段

### 阶段 1：骨架与文档

1. 创建插件目录。
2. 编写 `_manifest.json`。
3. 编写配置模型。
4. 编写 README。
5. 编写 SQLite 存储基础。

### 阶段 2：日程创建与确认

1. 命令入口。
2. Maisaka Tool 入口。
3. LLM 解析草稿。
4. 5 分钟确认。
5. 保存任务。
6. 列表、查看、暂停、恢复、删除。

### 阶段 3：调度与 Maisaka 触发

1. 后台调度器。
2. 到点任务执行。
3. 上下文构建。
4. `append_context`。
5. `trigger_proactive`。

### 阶段 4：日程兜底

1. 触发后观察消息。
2. 未发言时 LLM 兜底生成。
3. `send.text` 发送。
4. run 记录。

### 阶段 5：Tavily 联网检索

1. Tavily client。
2. 检索结果归一化。
3. LLM 压缩事实包。
4. 接入 research_digest 和 auto_proactive。

### 阶段 6：自动发起与频率函数

1. 目标扫描。
2. 频率函数。
3. LLM 判断。
4. 混合上下文源配置。
5. 自动触发 Maisaka。

### 阶段 7：RBAC 完善

1. 角色绑定。
2. 权限命令。
3. 操作审计。
4. 跨聊天流安全检查。

## 实现期验证事项

当前没有阻塞级产品疑问，只有几个实现时需要实测的细节：

1. SDK 序列化消息中如何稳定识别 bot 自己发送的消息。
   - 影响日程兜底是否误判。
   - 如果无法稳定识别，可能需要主程序增加 proactive task 状态或发送回执查询能力。

2. Tavily 返回字段会随套餐和参数略有不同。
   - 实现时必须按实际 API 响应做严格归一化。

3. 插件依赖安装流程需要验证：
   - Tavily HTTP 客户端固定使用 `httpx`。
   - cron 表达式解析固定使用 `croniter`。
   - 二者都需要写入 `_manifest.json` dependencies。

4. 自然语言时间解析策略固定为 LLM 输出带时区绝对时间，代码层做二次校验。

这些不是产品方向疑问，只是实现验证点。
