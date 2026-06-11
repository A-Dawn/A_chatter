# A_chatter 技术设计

中文名：进阶闲谈家

本文档面向实现，基于当前 MaiBot 源码和项目 `.venv` 中的 `maibot_sdk` 接口编写。产品计划见 `../../PLAN.md`，消息流转见 `MESSAGE_FLOW.md`，代码规范见 `CODE_STYLE.md`。

## 实现原则

1. 插件只通过 `maibot_sdk` 能力访问宿主，不直接导入主程序 `src.*`。
2. 记忆检索走 `ctx.knowledge.search()`，不直接访问 A_memorix 内部实现。
3. 聊天流解析走 `ctx.chat.*`，不自行计算 `session_id`。
4. 发送消息走 `ctx.send.*`，主动发言走 `ctx.maisaka.*`。
5. 插件状态和任务数据使用插件自有 SQLite，不进入主程序数据库迁移体系。
6. 出错时让错误清晰暴露到日志和命令响应，不用静默 fallback 掩盖核心问题。
7. 命令入口、Maisaka 工具入口、后台调度入口共享同一套业务服务。

## 源码与 SDK 对齐

### SDK 入口

当前项目环境中的 SDK 位于：

```text
.venv/Lib/site-packages/maibot_sdk/
```

插件类继承 `MaiBotPlugin`，通过 `self.ctx` 访问能力代理。关键代理在 `maibot_sdk.context.PluginContext` 中初始化：

1. `ctx.maisaka`
2. `ctx.message`
3. `ctx.knowledge`
4. `ctx.llm`
5. `ctx.send`
6. `ctx.chat`
7. `ctx.config`
8. `ctx.api`

插件还需要使用 SDK 组件装饰器：

1. `@Command`
2. `@Tool`

`@Command` 用于 `/ac` 显式命令；`@Tool` 用于让 Maisaka 在自然语言聊天中调用插件能力。

### Maisaka 能力

SDK 文件：

```text
.venv/Lib/site-packages/maibot_sdk/capabilities/maisaka.py
```

可用方法：

```python
await self.ctx.maisaka.append_context(
    stream_id,
    [{"type": "text", "content": visible_text}],
    visible_text=visible_text,
    source_kind="plugin:a-chatter",
    message_id=message_id,
)

await self.ctx.maisaka.trigger_proactive(
    stream_id,
    intent,
    reason=reason,
    priority="high",
    metadata=metadata,
)
```

宿主注册位置：

```text
src/plugin_runtime/capabilities/registry.py
```

对应能力：

1. `maisaka.context.append`
2. `maisaka.proactive.trigger`

宿主实现：

```text
src/plugin_runtime/capabilities/core.py
```

实现行为：

1. `maisaka.context.append` 会把插件提供的 segments 转成宿主消息段，追加到目标 Maisaka runtime 的 `_chat_history`。
2. `maisaka.proactive.trigger` 会检查目标 stream_id 是否存在，然后调用 runtime 的 `enqueue_proactive_task`。

Maisaka runtime 位置：

```text
src/maisaka/runtime.py
```

`enqueue_proactive_task` 会：

1. 在聊天历史中追加 `<plugin_proactive_task>` 上下文。
2. 设置 proactive anchor。
3. 设置 `_force_next_timing_continue = True`。
4. 将 `"proactive"` 放入内部队列。

这意味着 A_chatter 不需要直接让模型发文本，优先把任务交给 Maisaka 主循环处理。

需要注意：当前 Maisaka 的思考由消息、timeout 或插件 proactive 触发，不是常驻后台自发思考模型。因此“bot 想发言就发言”的纯插件实现不能假设 Maisaka 会主动提供候选意图；候选意图必须由 A_chatter 在自动发起扫描中生成和筛选，再通过 `trigger_proactive` 唤醒 Maisaka。

### 插件 Tool 能力

SDK 文件：

```text
.venv/Lib/site-packages/maibot_sdk/components.py
```

`@Tool` 会把方法注册为插件 Tool 组件，参数可使用 `ToolParameterInfo` 列表或 dict schema。

示例形态：

```python
@Tool(
    "a_chatter_create_task_draft",
    description="根据用户自然语言创建 A_chatter 待确认任务草稿，不直接创建正式任务。",
    parameters={
        "type": "object",
        "properties": {
            "user_request": {"type": "string", "description": "用户原始自然语言需求"},
            "target": {"type": "string", "description": "可选目标聊天，格式 platform:group/private:id"},
        },
        "required": ["user_request"],
    },
    visibility="visible",
)
async def handle_create_task_draft(self, user_request: str = "", target: str = "", **kwargs: Any) -> dict[str, Any]:
    ...
```

宿主侧工具接入链路：

1. `src/maisaka/runtime.py` 在 runtime 初始化时注册 `PluginToolProvider`。
2. `src/plugin_runtime/tool_provider.py` 从 `component_query_service` 获取插件 Tool。
3. `src/maisaka/reasoning_engine.py` 的 Action Loop 构造工具定义并让 planner 选择调用。
4. `src/plugin_runtime/component_query.py` 将 Maisaka 工具调用转发到插件 runner 的 `plugin.invoke_tool`。

工具可见性：

1. 插件工具默认会进入 deferred tools 池。
2. `metadata.visibility = "visible"` 的插件工具会直接暴露给 Action Loop。
3. 非 visible 工具需要 Maisaka 先通过 `tool_search` 发现。

A_chatter 建议：

1. `a_chatter_create_task_draft` visible。
2. `a_chatter_confirm_task` visible。
3. 查询和管理类工具 deferred。

工具执行上下文：

宿主会向插件工具参数补充：

1. `stream_id`
2. `chat_id`
3. `group_id`
4. `user_id`
5. `platform`

这些字段由 `component_query_service` 从 `ToolExecutionContext` 提取。A_chatter 用它们判断 actor、默认目标聊天流和 RBAC。

### 消息能力

SDK 文件：

```text
.venv/Lib/site-packages/maibot_sdk/capabilities/message.py
```

常用方法：

```python
messages = await self.ctx.message.get_recent(chat_id=stream_id, limit=30)
readable = await self.ctx.message.build_readable(
    messages,
    timestamp_mode="relative",
    truncate=True,
)
count = await self.ctx.message.count_new(chat_id=stream_id, since=str(started_at))
```

宿主能力实现：

```text
src/plugin_runtime/capabilities/data.py
```

关键能力：

1. `message.get_recent`
2. `message.get_by_time_in_chat`
3. `message.count_new`
4. `message.build_readable`

用途：

1. 自动发起前读取最近聊天。
2. 日程触发后观察是否已有新消息。
3. 将消息列表转换成 LLM 可读文本。

实现注意：

1. `get_recent` 的入参使用 `chat_id`，也就是真实 stream_id。
2. 返回消息的具体字段需要在实现阶段用真实运行样本确认，尤其是 bot 自己发送消息的识别字段。

### 记忆能力

SDK 文件：

```text
.venv/Lib/site-packages/maibot_sdk/capabilities/knowledge.py
```

调用方式：

```python
content = await self.ctx.knowledge.search(query, limit=5)
```

宿主能力实现：

```text
src/plugin_runtime/capabilities/data.py
```

底层会调用：

```text
src/services/memory_service.py
```

`memory_service.search()` 再通过 A_memorix host service 执行长期记忆检索。

当前 SDK 的 `knowledge.search` 返回值经过 `PluginContext` 归一化后通常是 `content` 字符串，而不是完整 hits。上下文注入直接使用该文本。

### LLM 能力

SDK 文件：

```text
.venv/Lib/site-packages/maibot_sdk/capabilities/llm.py
```

调用方式：

```python
result = await self.ctx.llm.generate(
    prompt=prompt,
    model="utils",
    temperature=0.2,
    max_tokens=1200,
)
```

返回结构通常包含：

1. `success`
2. `response`
3. `reasoning`
4. `model`

A_chatter 使用场景：

1. 解析自然语言日程。
2. 生成二次确认文案。
3. 自动发起前判断是否值得说。
4. Tavily 检索结果压缩。
5. 日程任务未发言时生成兜底文本。

### 发送能力

SDK 文件：

```text
.venv/Lib/site-packages/maibot_sdk/capabilities/send.py
```

调用方式：

```python
await self.ctx.send.text(
    text,
    stream_id,
    typing=True,
    storage_message=True,
    sync_to_maisaka_history=True,
    maisaka_source_kind="plugin:a-chatter:fallback",
)
```

用途：

1. 命令响应。
2. 硬提醒。
3. 日程兜底发言。

注意：

1. `send.text` 返回布尔值。
2. 日程兜底建议设置 `sync_to_maisaka_history=True`，让 Maisaka 后续上下文能看到这条消息。

### 聊天流能力

SDK 文件：

```text
.venv/Lib/site-packages/maibot_sdk/capabilities/chat.py
```

调用方式：

```python
stream = await self.ctx.chat.get_stream_by_group_id(group_id, platform="qq")
stream = await self.ctx.chat.get_stream_by_user_id(user_id, platform="qq")
```

宿主实现位于：

```text
src/plugin_runtime/capabilities/data.py
```

实现约束：

1. 查询已有群聊优先使用 `get_stream_by_group_id`。
2. 查询已有私聊优先使用 `get_stream_by_user_id`。
3. 当前插件不主动创建新聊天流；目标不存在时按错误处理策略提示用户先让 bot 与目标建立会话。
4. 不允许插件自行调用 `SessionUtils.calculate_session_id`。

## Manifest 能力声明

`_manifest.json` 至少声明：

```json
{
  "capabilities": [
    "send.text",
    "llm.generate",
    "chat.get_all_streams",
    "chat.get_group_streams",
    "chat.get_private_streams",
    "chat.get_stream_by_group_id",
    "chat.get_stream_by_user_id",
    "message.get_recent",
    "message.get_by_time_in_chat",
    "message.count_new",
    "message.build_readable",
    "knowledge.search",
    "maisaka.context.append",
    "maisaka.proactive.trigger"
  ]
}
```

Tool 组件不写在 `capabilities` 里，而是在插件代码中用 `@Tool` 声明，运行时注册到宿主组件表。

Tavily HTTP 客户端固定使用 `httpx`，cron 表达式解析固定使用 `croniter`。二者都需要在 manifest dependencies 中声明。

## 模块设计

### `plugin.py`

职责：

1. 定义 `AChatterPlugin(MaiBotPlugin)`。
2. 绑定配置模型 `AChatterConfig`。
3. 在 `on_load` 初始化服务。
4. 在 `on_unload` 停止 scheduler。
5. 在 `on_config_update` 刷新运行时配置。
6. 注册命令入口。
7. 注册 A_chatter Tool 入口。

建议保持薄入口：

```python
class AChatterPlugin(MaiBotPlugin):
    config_model = AChatterConfig

    async def on_load(self) -> None:
        self._runtime = AChatterRuntime(self.ctx, self.config)
        await self._runtime.start()

    async def on_unload(self) -> None:
        if self._runtime is not None:
            await self._runtime.stop()
```

Tool 方法也放在 `plugin.py`，但只做参数整理和转发：

```python
@Tool(...)
async def handle_create_task_draft(self, user_request: str = "", **kwargs: Any) -> dict[str, Any]:
    return await self._runtime.tools.create_task_draft(user_request=user_request, context=kwargs)
```

### `a_chatter/config.py`

职责：

1. 定义 SDK 配置模型。
2. 使用 `PluginConfigBase` 和 `Field`。
3. 保持 UI 分组。

主要配置组：

1. `PluginSectionConfig`
2. `PermissionConfig`
3. `WhitelistConfig`
4. `FrequencyConfig`
5. `TargetConfig`
6. `TavilyConfig`
7. `ConfirmationConfig`
8. `ProactiveConfig`

### `a_chatter/models.py`

职责：

1. 定义业务 dataclass 或 pydantic model。
2. 不依赖 SDK。

建议模型：

1. `TaskType`
2. `TaskStatus`
3. `ChatTarget`
4. `ScheduleSpec`
5. `TaskDraft`
6. `AChatterTask`
7. `TaskRun`
8. `RbacSubject`
9. `RbacBinding`
10. `FrequencyContext`
11. `ContextBundle`
12. `TavilyResult`

### `a_chatter/storage.py`

职责：

1. SQLite 初始化。
2. schema migration。
3. 任务 CRUD。
4. pending confirmation CRUD。
5. run 记录。
6. target state 记录。

建议：

1. 使用标准库 `sqlite3`，通过 `asyncio.to_thread` 包装阻塞操作。
2. 或使用 `aiosqlite`，但需要声明依赖。
3. schema 版本写入 `meta` 表。

不要使用主程序 `database.query` 能力来保存插件自定义任务，因为宿主能力面向主程序 SQLModel，不适合插件自定义表。

### `a_chatter/parser.py`

职责：

1. 构建 LLM 解析 prompt。
2. 解析 JSON。
3. 校验草稿。
4. 生成确认文案。

接口：

```python
class NaturalLanguageTaskParser:
    async def parse(self, text: str, context: ParseContext) -> TaskDraft: ...
    async def build_confirmation_text(self, draft: TaskDraft) -> str: ...
```

要求：

1. 所有时间输出必须是带时区绝对时间。
2. 低置信度或有歧义时返回追问。
3. 不直接保存任务。

### `a_chatter/rbac.py`

职责：

1. 判断用户角色。
2. 判断目标权限。
3. 管理白名单。
4. 管理跨聊天流权限。

接口：

```python
class RbacService:
    async def can_create_task(self, actor: Actor, target: ChatTarget) -> PermissionResult: ...
    async def can_manage_task(self, actor: Actor, task: AChatterTask) -> PermissionResult: ...
```

权限来源：

1. 插件配置。
2. SQLite 中的 `rbac_bindings`。
3. 当前聊天上下文。

### `a_chatter/frequency.py`

职责：

1. 计算自动主动发起概率。
2. 处理安静时段 factor。
3. 计算下一次扫描建议时间。
4. 为 `self_reflection` 等自动发起来源提供同一套密度门控。

核心函数：

```python
def compute_trigger_probability(
    *,
    global_frequency: float,
    target_frequency: float,
    source_frequency: float,
    quiet_factor: float,
    elapsed_seconds: float,
    base_interval_seconds: float,
    min_interval_seconds: float,
    max_probability: float,
    intent_score: float,
) -> float:
    ...
```

规则：

1. 频率越高，概率越高。
2. elapsed 越长，概率越高。
3. `effective_frequency <= 0` 时返回 0。
4. `elapsed_seconds < min_interval_seconds` 时返回 0。
5. 结果限制在 `[0, max_probability]`，再乘 intent score。
6. `self_reflection` 来源不得绕过该函数。

### `a_chatter/context_builder.py`

职责：

1. 收集 history。
2. 收集 memory。
3. 收集 web facts。
4. 组装 `visible_text`。
5. 组装 proactive intent。

接口：

```python
class ContextBuilder:
    async def build_for_schedule(self, task: AChatterTask, quiet: QuietState) -> ContextBundle: ...
    async def build_for_auto(self, target: ChatTarget, source: str) -> ContextBundle: ...
    async def build_preliminary_for_auto(self, target: ChatTarget, source: str) -> ContextBundle: ...
```

实现细节：

1. history 调用 `ctx.message.get_recent` 和 `ctx.message.build_readable`。
2. memory 调用 `ctx.knowledge.search`。
3. web 调用 `TavilyClient`，再用 `ctx.llm.generate` 压缩。
4. subscription 读取任务或配置中的订阅主题，并按需要交给 web source 检索。
5. 安静时段只在日程任务上下文中追加风格提示。
6. 所有主动发起判断和完整上下文都要注入 persona context。
7. `source="self_reflection"` 时，persona context 是候选意图生成的驱动材料；普通 source 中 persona 只影响判断和表达，不作为发起理由。

### `a_chatter/tavily_client.py`

职责：

1. 调用 Tavily HTTP API。
2. 超时处理。
3. 响应归一化。
4. URL 去重。

接口：

```python
class TavilyClient:
    async def search(self, query: str, *, max_results: int) -> list[TavilyResult]: ...
```

错误策略：

1. API key 缺失：明确返回配置错误。
2. HTTP 非 2xx：记录状态码和响应摘要。
3. 返回字段缺失：按严格归一化处理，缺必需字段则跳过该条。

### `a_chatter/proactive.py`

职责：

1. 执行 `append_context`。
2. 执行 `trigger_proactive`。
3. 日程驱动任务观察是否发言。
4. 需要时执行兜底发送。

接口：

```python
class ProactiveExecutor:
    async def trigger_schedule(self, task: AChatterTask, bundle: ContextBundle) -> TaskRunResult: ...
    async def trigger_auto(self, target: ChatTarget, bundle: ContextBundle) -> TaskRunResult: ...
```

日程驱动流程：

1. 记录 `started_at`。
2. `ctx.maisaka.append_context(...)`。
3. `ctx.maisaka.trigger_proactive(...)`。
4. 等待 `maisaka_wait_seconds`。
5. 检测是否已有 bot 发言。
6. 如无发言，LLM 生成兜底并 `ctx.send.text(...)`。

自动发起流程：

1. 接收已经通过频率密度和 LLM 判断的 `ContextBundle`。
2. `append_context`。
3. `trigger_proactive`。
4. 不兜底。

`self_reflection` 不单独实现一套执行器。它作为 `trigger_auto` 的 `source` 输入，和 `history`、`memory`、`web`、`subscription` 等来源共用自动发起流程。该来源不创建持久任务，不需要二次确认，不兜底，只记录 run/audit。

`persona` 不作为普通自动发起 source。实现时应把 persona context 作为判断和生成上下文注入：

1. `history` / `memory` / `web` / `subscription`：source 提供发起理由，persona 影响 LLM 判断和表达。
2. `self_reflection`：persona context 作为 source driver，用于生成候选意图。
3. `trigger_auto` 最终注入 Maisaka 的上下文必须包含 persona context。

### `a_chatter/scheduler.py`

职责：

1. 后台调度循环。
2. due task 查询。
3. 自动发起扫描。
4. 单任务锁。
5. 停止与取消。

接口：

```python
class AChatterScheduler:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

并发要求：

1. `on_unload` 必须等待后台任务退出。
2. 任务执行需要 per-task lock。
3. 同一目标自动发起需要 target lock，避免多来源同时触发。
4. 长耗时 Tavily 和 LLM 调用要有超时。

### `a_chatter/commands.py`

职责：

1. `/ac` 命令解析。
2. 创建草稿。
3. 确认/取消。
4. 列表/查看。
5. 暂停/恢复/删除。
6. 状态查询。

命令函数由 `plugin.py` 用 `@Command` 装饰器暴露，实际逻辑转发给 command service。

### `a_chatter/tools.py`

职责：

1. 承接 Maisaka Tool 调用。
2. 解析工具参数和 SDK 注入上下文。
3. 调用 parser、rbac、storage 等共享服务。
4. 返回结构化工具结果，供 Maisaka 自然转述。

工具服务不直接发送普通聊天回复，除非工具语义明确要求；大部分场景只返回 `content` 和结构化字段给 Maisaka。

建议接口：

```python
class AChatterToolService:
    async def create_task_draft(self, user_request: str, context: dict[str, Any]) -> dict[str, Any]: ...
    async def confirm_task(self, draft_id: str, context: dict[str, Any]) -> dict[str, Any]: ...
    async def cancel_draft(self, draft_id: str, context: dict[str, Any]) -> dict[str, Any]: ...
    async def list_tasks(self, target: str, context: dict[str, Any]) -> dict[str, Any]: ...
    async def manage_task(self, task_id: str, action: str, context: dict[str, Any]) -> dict[str, Any]: ...
    async def query_status(self, scope: str, context: dict[str, Any]) -> dict[str, Any]: ...
```

## 数据流

### 命令创建任务

```text
用户命令
-> Command handler
-> RBAC 初步检查
-> LLM parser 生成 TaskDraft
-> 目标聊天流解析
-> RBAC 完整检查
-> 保存 pending confirmation
-> send.text 确认文案
```

确认：

```text
用户 /ac 确认
-> 查 pending confirmation
-> 检查 5 分钟 TTL
-> 保存 task
-> send.text 创建成功
```

### Maisaka 工具创建任务

```text
用户自然语言表达日程/提醒需求
-> Maisaka planner 选择 a_chatter_create_task_draft
-> PluginToolProvider 转发 plugin.invoke_tool
-> Tool service 提取 stream_id/platform/user_id/group_id
-> RBAC 初步检查
-> LLM parser 生成 TaskDraft
-> 目标聊天流解析
-> RBAC 完整检查
-> 保存 pending confirmation
-> 返回 requires_user_confirmation=true 和 task_preview
-> Maisaka 自然转述确认摘要
```

确认：

```text
用户自然回复“确认”
-> Maisaka planner 选择 a_chatter_confirm_task
-> Tool service 查 pending confirmation
-> 检查 5 分钟 TTL
-> 保存正式 task
-> 返回任务创建结果
-> Maisaka 自然回复用户
```

命令确认和工具确认操作同一张 pending confirmation 表。

### 日程任务执行

```text
Scheduler due task
-> ContextBuilder.build_for_schedule
-> ProactiveExecutor.trigger_schedule
-> append_context
-> trigger_proactive
-> wait
-> observe sent message
-> fallback if needed
-> record run
-> compute next_run_at
```

### 自动发起执行

```text
Scheduler scan target
-> choose source: history / memory / web / subscription / self_reflection
-> FrequencyService compute probability
-> random hit
-> ContextBuilder preliminary context + persona context
-> LLM judge should_speak / generate candidate intent
-> FrequencyService final gate with intent_score
-> ContextBuilder full context + persona context
-> ProactiveExecutor.trigger_auto
-> record run
```

说明：

1. `self_reflection` 只是 `source` 的一个取值，不是独立执行链路。
2. 普通 source 的发起理由来自明确锚点，persona 只影响判断和表达。
3. 当 `source=self_reflection` 时，候选意图由 persona context 驱动生成，不由 Maisaka 后台自发产生。
4. 所有自动发起来源共用频率密度流程。
5. Maisaka 被唤醒后仍可根据自身 planner 决定表达方式。

## Bot 发言观察

当前计划中的最大实现验证点是“如何稳定判断 Maisaka 是否已经发言”。

建议分两层：

1. 优先通过 `ctx.message.get_recent` 获取触发后的消息，判断是否存在 bot 发送者。
2. 如果 SDK 消息中无法稳定识别 bot，则退化为：
   - 检查触发后是否出现任何新消息。
   - 若出现新消息但不能确认是否 bot，说不准是否需要兜底时不发送兜底，避免重复发言。
   - 在 run 记录中标记 `fallback_skipped_reason = "unknown_sender_identity"`。

如需进一步提高精度，可考虑请求主程序增加能力：

1. proactive task 状态查询。
2. 按 source_kind 查询发送消息。
3. send/proactive 回执事件。

## 时间与时区

默认时区：

```text
Asia/Shanghai
```

实现要求：

1. LLM 解析输出必须是带时区 ISO 时间。
2. 代码层二次校验时间是否合法。
3. SQLite 存 UTC timestamp 或 ISO UTC 字符串。
4. 展示给用户时转回目标配置时区。
5. 当前时间必须由代码注入 prompt，不能让 LLM 自己猜。

## 配置热更新

`on_config_update` 触发后：

1. 更新 runtime config。
2. 刷新 Tavily client。
3. 刷新频率参数。
4. 刷新 target 配置。
5. 不重建 SQLite schema。
6. 不清空 pending confirmations，除非配置关闭插件。

如果 `plugin.enabled = false`：

1. 命令只允许 `/ac 状态`。
2. scheduler 暂停扫描和任务执行。
3. 不删除已有任务。

## 日志与审计

建议 logger 名称使用 SDK 默认 `plugin.<plugin_id>`。

关键日志：

1. 插件加载/卸载。
2. scheduler 启动/停止。
3. 任务创建、确认、删除。
4. RBAC 拒绝。
5. Tavily 请求失败。
6. LLM JSON 解析失败。
7. Maisaka proactive 触发失败。
8. 日程兜底执行。

run 表记录用于用户可见审计，不应只写日志。

## 测试策略

### 不依赖宿主的纯单元测试

1. `frequency.py`
2. `rbac.py`
3. `storage.py`
4. `tavily_client.py` 响应归一化
5. `parser.py` JSON 校验

### SDK 调用 mock 测试

参考 `plugins/mute_report_murmur/tests/test_plugin.py`，构造 fake ctx：

1. fake `ctx.maisaka.append_context`
2. fake `ctx.maisaka.trigger_proactive`
3. fake `ctx.message.get_recent`
4. fake `ctx.knowledge.search`
5. fake `ctx.llm.generate`
6. fake `ctx.send.text`

覆盖：

1. 日程任务触发 Maisaka。
2. Maisaka 未发言后兜底。
3. 自动发起不兜底。
4. `self_reflection` 来源作为 `auto_proactive` source 复用频率密度函数。
5. `self_reflection` 未通过 LLM 判断时不触发 Maisaka。
6. Tavily 未配置时不调用外网。
7. RBAC 拒绝跨聊天流创建。

## 实现顺序建议

1. `_manifest.json` 和空插件入口。
2. `config.py`。
3. `models.py`。
4. `storage.py`。
5. `rbac.py`。
6. `frequency.py`。
7. `parser.py` 的 LLM prompt 与 JSON 校验。
8. `commands.py` 创建/确认/列表。
9. `scheduler.py` 执行 due task。
10. `context_builder.py` history + memory。
11. `proactive.py` append + trigger。
12. 日程兜底。
13. `tavily_client.py`。
14. 自动发起扫描。
15. `self_reflection` 自动发起来源。
16. 完整测试和 README。

## 需要实现时验证的事项

1. SDK 消息结构中 bot 自身消息的可靠识别字段。
2. Tavily 实际响应字段。
3. 插件 dependencies 安装 `httpx` 和 `croniter` 的流程。
