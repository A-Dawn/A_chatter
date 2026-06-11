# A_chatter 消息流转图

中文名：进阶闲谈家

本文档描述 A_chatter 的主要消息和任务流转。技术实现细节见 `TECHNICAL_DESIGN.md`，产品计划见 `../../PLAN.md`。

## 总览

```mermaid
flowchart TD
    User["用户消息"] --> Host["MaiBot 消息接收链路"]
    Host --> Maisaka["Maisaka planner"]
    Host --> Command["A_chatter Command 入口"]

    Maisaka --> ToolSearch{"是否需要 A_chatter 工具"}
    ToolSearch -->|是| Tool["A_chatter Tool 入口"]
    ToolSearch -->|否| NormalReply["Maisaka 常规回复链"]

    Command --> Shared["共享业务服务"]
    Tool --> Shared

    Shared --> Parser["LLM 解析与确认文案"]
    Shared --> RBAC["RBAC / 白名单 / 目标校验"]
    Shared --> Storage["SQLite 任务与草稿存储"]

    Storage --> Scheduler["后台调度器"]
    Scheduler --> Context["上下文构建器"]
    Context --> History["聊天历史"]
    Context --> Memory["A_memorix 记忆检索"]
    Context --> Web["Tavily 联网检索"]
    Context --> Proactive["Maisaka 主动触发"]

    Proactive --> Append["ctx.maisaka.append_context"]
    Append --> Trigger["ctx.maisaka.trigger_proactive"]
    Trigger --> Maisaka

    Scheduler --> Reminder["硬提醒发送"]
    Reminder --> Send["ctx.send.text"]
```

## 命令创建任务

```mermaid
sequenceDiagram
    participant U as 用户
    participant C as A_chatter Command
    participant R as RBAC
    participant L as LLM Parser
    participant S as SQLite
    participant Send as ctx.send.text

    U->>C: /ac 新增 明天 20:00 提醒我交报告
    C->>R: 检查当前用户和目标权限
    R-->>C: 允许 / 拒绝
    C->>L: 解析自然语言任务并生成确认话术
    L-->>C: TaskDraft + 自然确认文案
    C->>S: 保存 pending confirmation
    C->>Send: 发送确认消息
    Send-->>U: 自然确认草稿

    U->>C: /ac 确认
    C->>S: 读取并校验 5 分钟内的草稿
    C->>R: 完整权限校验
    C->>S: 保存正式 task
    C->>Send: 发送创建成功消息
    Send-->>U: 已创建任务
```

用户也可以直接回复“确认”“就这样”“算了”等自然语言。该消息会在 `chat.receive.after_process` Hook 中被 A_chatter 识别；命中确认或取消后，插件发送结果并中止后续聊天主链，避免 Maisaka 再把确认消息当作普通聊天处理。

## Maisaka 自然语言工具创建任务

```mermaid
sequenceDiagram
    participant U as 用户
    participant M as Maisaka planner
    participant TP as PluginToolProvider
    participant T as A_chatter Tool
    participant R as RBAC
    participant L as LLM Parser
    participant S as SQLite

    U->>M: 明天晚上八点提醒我交报告
    M->>TP: 调用 a_chatter_create_task_draft
    TP->>T: plugin.invoke_tool + stream_id/user_id/platform/group_id
    T->>R: 初步权限检查
    T->>L: 解析用户自然语言需求并生成确认话术
    L-->>T: TaskDraft + 置信度 + 歧义项 + 自然确认文案
    T->>R: 完整权限和目标校验
    T->>S: 保存 pending confirmation
    T-->>TP: requires_user_confirmation=true + task_preview
    TP-->>M: 工具结果
    M-->>U: 使用确认文案自然询问用户

    U->>M: 确认 / 就这样 / 算了
    M->>TP: 调用 a_chatter_confirm_task 或 a_chatter_cancel_draft
    TP->>T: plugin.invoke_tool + 上下文
    T->>S: 读取 pending confirmation
    T->>S: 保存正式 task
    T-->>M: 创建成功
    M-->>U: 自然回复任务已设置
```

## 日程驱动主动发言

```mermaid
sequenceDiagram
    participant Sch as Scheduler
    participant S as SQLite
    participant CB as ContextBuilder
    participant Msg as ctx.message
    participant Mem as ctx.knowledge
    participant Tav as Tavily
    participant P as ProactiveExecutor
    participant MS as ctx.maisaka
    participant M as Maisaka
    participant Send as ctx.send.text

    Sch->>S: 查询到期 schedule_proactive
    Sch->>CB: 构建日程上下文
    CB->>Msg: 获取最近聊天历史
    CB->>Mem: 检索 A_memorix 记忆
    CB->>Tav: 可选联网检索
    CB-->>Sch: ContextBundle
    Sch->>P: 执行日程主动任务
    P->>MS: append_context
    P->>MS: trigger_proactive(priority=high)
    MS->>M: 写入 proactive 任务并唤醒
    P->>Msg: 等待后观察是否已有 bot 发言
    alt Maisaka 已发言
        P->>S: 记录 run 成功
    else 未观察到发言
        P->>Send: LLM 兜底文本后 send.text
        P->>S: 记录 run + used_fallback
    end
```

## 自动主动发起

```mermaid
flowchart TD
    Tick["Scheduler tick"] --> Target["扫描启用目标"]
    Target --> Source["选择自动发起来源"]
    Source --> History["history"]
    Source --> Memory["memory"]
    Source --> WebSource["web"]
    Source --> Subscription["subscription"]
    Source --> SelfReflection["self_reflection"]

    History --> Freq["计算初步频率函数"]
    Memory --> Freq
    WebSource --> Freq
    Subscription --> Freq
    SelfReflection --> Freq

    Freq --> Chance{"概率命中?"}
    Chance -->|否| Skip1["记录跳过"]
    Chance -->|是| PreContext["构建初步上下文"]
    PreContext --> PersonaCtx["注入 persona context"]
    PersonaCtx --> Judge["LLM 判断是否值得说 / 生成候选意图"]
    Judge --> Speak{"should_speak?"}
    Speak -->|否| Skip2["记录 LLM 跳过原因"]
    Speak -->|是| FinalGate["intent_score 参与最终密度放行"]
    FinalGate --> GateOk{"放行?"}
    GateOk -->|否| Skip3["记录密度跳过"]
    GateOk -->|是| FullContext["构建完整上下文"]
    FullContext --> PersonaOut["附加 persona context"]
    PersonaOut --> Append["ctx.maisaka.append_context"]
    Append --> Trigger["ctx.maisaka.trigger_proactive"]
    Trigger --> Run["记录 run"]
```

说明：`persona` 是判断和生成上下文，不是普通自动发起 source。普通 source 的发起理由来自 history、memory、web、subscription 等明确锚点；`self_reflection` 是 persona-driven source，它不假设 Maisaka 常驻后台自发思考，候选意图由 A_chatter 在统一自动发起流程中生成并筛选。

## 硬提醒

```mermaid
sequenceDiagram
    participant Sch as Scheduler
    participant S as SQLite
    participant Send as ctx.send.text

    Sch->>S: 查询到期 reminder
    Sch->>Send: 发送提醒文本
    Send-->>Sch: success / failure
    Sch->>S: 记录 run 并计算下一次触发
```

## 关键约束

1. 命令入口和 Maisaka Tool 入口都必须走二次确认。
2. 命令入口和 Maisaka Tool 入口共享 pending confirmation 表。
3. 业务模块不自行计算 `session_id`，目标聊天流解析走 `ctx.chat.*`。
4. 日程驱动主动发言必须产生发言，优先 Maisaka，必要时兜底 `send.text`。
5. 自动主动发起不兜底。
6. 安静时段对日程驱动任务只影响风格，不阻止发言。
7. `self_reflection` 属于 `auto_proactive` 来源，必须复用同一套频率密度流程。
8. 当前纯插件方案不假设 Maisaka 会在后台自行产生候选意图。
9. `persona` 必须参与主动发言判断和最终输出，但普通 source 不能只靠 persona 作为发起理由。
