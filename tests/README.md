# A_chatter 测试套件

## unit

纯单元测试，不依赖真实宿主或外部服务。覆盖频率函数、RBAC、SQLite 存储、Tavily 响应归一化和插件组件注册。

运行：

```bash
uv run pytest plugins/A_chatter/tests/unit -q
```

## functional

使用 fake SDK context 测试共享业务服务链路。覆盖命令创建草稿、确认、列表，Tool 创建与确认，到期提醒发送，以及日程主动任务触发 Maisaka。

运行：

```bash
uv run pytest plugins/A_chatter/tests/functional -q
```

## real_flow

使用 `AChatterPlugin` 实例走更接近宿主的生命周期流程：注入 context、设置配置、`on_load`、调用命令/Tool handler、`on_unload`。SQLite 路径会重定向到 pytest 临时目录。

运行：

```bash
uv run pytest plugins/A_chatter/tests/real_flow -q
```

## full_loop

使用 fake SDK context 跑完整闭环：命令创建草稿、用户确认、正式任务落库、调度器扫描到期任务、最终发送提醒或触发 Maisaka。该套件不调用真实外部服务。

运行：

```bash
uv run pytest plugins/A_chatter/tests/full_loop -q
```

## live_llm

通过父项目 LLM capability 真实调用模型，默认跳过。设置 `A_CHATTER_LIVE_LLM=1` 后执行。
调用链为 `PluginContext.llm.generate -> cap.call -> PluginRuntimeManager._cap_llm_generate -> src.services.llm_service.generate`，用于验证插件接入父项目模型配置和任务路由，而不是直连外部 SDK。

运行：

```bash
A_CHATTER_LIVE_LLM=1 uv run pytest plugins/A_chatter/tests/live_llm -q
```

真实 LLM 套件使用父项目 `model_config.toml` 中的 `utils` 任务模型。

输出判定标准：

1. LLM 返回内容必须能被 `NaturalLanguageTaskParser` 解析为 `TaskDraft`。
2. `task_type` 必须属于计划允许值。
3. `schedule.kind` 必须可执行；提醒样例预期为 `once`。
4. `run_at` 必须是带时区的绝对时间，并晚于当前时间。
5. 默认目标必须保持当前真实聊天流 `stream_id`，不能自行计算 session_id。
6. 置信度必须不低于 0.7，且无歧义项。
7. 确认文案必须保留二次确认语义。

## live_full_loop

真实调用父项目 LLM capability，再跑命令创建、确认、立即运行和最终发送请求记录。发送、消息、知识和 Maisaka 能力由测试 Host 记录，不会向外部聊天平台发送消息。

运行：

```bash
A_CHATTER_LIVE_LLM=1 uv run pytest plugins/A_chatter/tests/live_full_loop -q -s
```
