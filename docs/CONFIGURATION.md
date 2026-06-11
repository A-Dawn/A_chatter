# A_chatter 配置说明

本文档说明 A_chatter 进阶闲谈家的插件配置项、默认行为和常见配置方式。配置字段来自 `a_chatter/config.py` 中的 `AChatterConfig`。

## 基础说明

A_chatter 的默认策略偏保守：

1. 插件默认启用。
2. 普通用户默认可以在自己的私聊创建个人任务。
3. 普通用户默认不能创建群聊任务。
4. 普通用户默认不能跨聊天流创建任务。
5. 白名单默认启用，但白名单列表为空时表示不额外限制。
6. Tavily 默认启用，但未配置 API Key 时不会执行联网检索。
7. 日程主动发言默认等待 Maisaka 发言，若未观察到发言则启用兜底发送。

目标格式统一为：

```text
qq:private:10000
qq:group:123456
```

## plugin

```toml
[plugin]
enabled = true
config_version = "0.1.0"
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否启用 A_chatter。关闭后不会创建新草稿，也不会执行调度。 |
| `config_version` | `"0.1.0"` | 配置版本标识。 |

## permissions

```toml
[permissions]
super_admins = []
default_allow_private_schedule = true
default_allow_group_schedule = false
allow_cross_stream_by_default = false
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `super_admins` | `[]` | 超级管理员，格式为 `platform:user_id`，例如 `qq:10000`。 |
| `default_allow_private_schedule` | `true` | 是否允许普通用户为自己的私聊创建任务。 |
| `default_allow_group_schedule` | `false` | 是否允许普通用户创建群聊任务。 |
| `allow_cross_stream_by_default` | `false` | 是否允许普通用户跨聊天流创建任务。 |

建议：

1. 私聊提醒可以保持默认。
2. 群聊任务建议优先配置 `super_admins` 或白名单后再开放。
3. `allow_cross_stream_by_default` 风险较高，建议只在可信环境开启。

## whitelist

```toml
[whitelist]
enabled = true
allowed_users = []
allowed_groups = []
allowed_private_users = []
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否启用白名单判断。 |
| `allowed_users` | `[]` | 允许使用插件的用户，格式 `qq:10000`。为空时不限制用户。 |
| `allowed_groups` | `[]` | 允许作为群聊任务目标的群，格式 `qq:123456`。为空时不限制群目标。 |
| `allowed_private_users` | `[]` | 允许作为私聊主动发言目标的用户，格式 `qq:10000`。为空时不限制私聊目标。 |

注意：

1. 只要对应列表非空，就会变成显式允许列表。
2. `super_admins` 不受普通白名单限制。

## frequency

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

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `global_frequency` | `1.0` | 全局主动发言密度倍率。越高越容易触发自动发起。 |
| `base_interval_seconds` | `3600` | 频率为 1.0 时的基础时间尺度。 |
| `min_interval_seconds` | `300` | 同一目标自动主动发起硬间隔。 |
| `max_probability` | `0.85` | 单次扫描概率上限。 |
| `history_source_frequency` | `0.8` | 聊天历史来源密度倍率。 |
| `memory_source_frequency` | `0.8` | 记忆来源密度倍率。 |
| `web_source_frequency` | `0.6` | 联网来源密度倍率。 |
| `subscription_source_frequency` | `0.7` | 订阅来源密度倍率。 |
| `self_reflection_source_frequency` | `0.7` | 自省来源密度倍率。 |

频率不是简单每日上限，而是概率密度参数。实际触发还会经过目标频率、来源频率、安静时段因子、距离上次触发时间和 LLM 意图评分共同计算。

## targets

`targets` 是目标聊天流的自动主动发起配置列表。

```toml
[[targets]]
target = "qq:group:123456"
enabled = true
frequency = 1.0
quiet_hours_enabled = false
quiet_hours = []
quiet_mode = "block_auto"
max_auto_runs_per_day = 6
max_schedule_fallbacks_per_day = 6
enabled_sources = ["history", "memory", "web", "subscription", "self_reflection"]
persona_context_enabled = true
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `target` | `""` | 目标，格式 `qq:group:123456` 或 `qq:private:10000`。 |
| `enabled` | `true` | 是否启用该目标的自动主动发起。 |
| `frequency` | `1.0` | 该目标主动发言密度倍率。 |
| `quiet_hours_enabled` | `false` | 是否启用安静时段。 |
| `quiet_hours` | `[]` | 安静时段列表，例如 `["00:00-08:00"]`。 |
| `quiet_mode` | `"block_auto"` | 安静时段模式：`style_only`、`reduce`、`block_auto`。 |
| `max_auto_runs_per_day` | `6` | 每日自动主动发起次数上限。 |
| `max_schedule_fallbacks_per_day` | `6` | 每日日程兜底次数上限。 |
| `enabled_sources` | 全部来源 | 自动主动发言来源。 |
| `persona_context_enabled` | `true` | 是否注入插件侧 persona context。 |

`enabled_sources` 支持：

```text
history
memory
web
subscription
self_reflection
```

当前说明：

1. `history`、`memory`、`web` 和 `self_reflection` 已接入自动发起框架。
2. `subscription` 作为来源名称已预留，订阅主题的管理和存储仍需继续完善。
3. `self_reflection` 是 persona-driven 的自动发起来源，不是独立执行链路。

## tavily

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

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否启用 Tavily 联网检索。 |
| `api_key` | `""` | Tavily API Key。 |
| `endpoint` | Tavily Search API | Tavily Search API 地址。 |
| `max_results` | `5` | 默认检索结果数。 |
| `search_depth` | `"basic"` | 检索深度。 |
| `include_answer` | `true` | 是否请求 Tavily answer。 |
| `include_raw_content` | `false` | 是否请求原始正文。 |
| `timeout_seconds` | `20` | HTTP 超时时间。 |

未配置 `api_key` 时，联网任务不会静默伪造结果，而会在上下文中明确说明联网检索未执行。

## confirmation

```toml
[confirmation]
pending_ttl_seconds = 300
max_pending_per_user = 3
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `pending_ttl_seconds` | `300` | 待确认草稿有效期。 |
| `max_pending_per_user` | `3` | 单用户最大待确认草稿数。 |

所有自然语言创建入口都会先生成待确认草稿，用户需要回复 `/ac 确认` 或 `/ac 确认 <草稿ID>` 才会创建正式任务。

## proactive

```toml
[proactive]
maisaka_wait_seconds = 90
fallback_enabled = true
fallback_model_task = "utils"
fallback_max_tokens = 300
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `maisaka_wait_seconds` | `90` | 日程主动任务触发 Maisaka 后等待发言的秒数。 |
| `fallback_enabled` | `true` | 等待后未观察到发言时，是否启用 LLM 兜底发送。 |
| `fallback_model_task` | `"utils"` | 兜底发言使用的父项目模型任务。 |
| `fallback_max_tokens` | `300` | 兜底发言最大 token。 |

日程主动任务是“必须发言”任务。安静时段只影响表达风格，不会让日程主动任务放弃发言。

## scheduler

```toml
[scheduler]
tick_seconds = 20
auto_scan_seconds = 300
history_limit = 30
memory_limit = 5
```

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `tick_seconds` | `20` | 后台调度 tick 间隔。 |
| `auto_scan_seconds` | `300` | 自动主动发起扫描间隔。 |
| `history_limit` | `30` | 构建上下文时读取的最近消息条数。 |
| `memory_limit` | `5` | 长期记忆检索数量上限。 |

## 常见配置

### 只允许私聊提醒

保持默认即可：

```toml
[permissions]
default_allow_private_schedule = true
default_allow_group_schedule = false
allow_cross_stream_by_default = false
```

### 指定管理员管理群任务

```toml
[permissions]
super_admins = ["qq:10000"]
default_allow_group_schedule = false
allow_cross_stream_by_default = false
```

超级管理员可以创建跨聊天流任务。

### 允许某个群创建群任务

```toml
[permissions]
default_allow_group_schedule = true

[whitelist]
enabled = true
allowed_groups = ["qq:123456"]
```

如果 `allowed_users` 也配置为非空，则只有列表中的用户可以使用插件。

### 为群聊启用自动主动发起

```toml
[[targets]]
target = "qq:group:123456"
enabled = true
frequency = 1.0
enabled_sources = ["history", "memory", "self_reflection"]
max_auto_runs_per_day = 4
persona_context_enabled = true
```

### 安静时段减少自动发起

```toml
[[targets]]
target = "qq:group:123456"
enabled = true
quiet_hours_enabled = true
quiet_hours = ["00:00-08:00"]
quiet_mode = "reduce"
```

`quiet_mode` 可选值：

| 值 | 行为 |
| --- | --- |
| `block_auto` | 安静时段阻止自动主动发起。 |
| `reduce` | 安静时段降低自动主动发起概率。 |
| `style_only` | 不降低概率，只影响日程主动任务表达风格。 |

### 关闭联网检索

```toml
[tavily]
enabled = false
api_key = ""
```

关闭后，非联网提醒和主动发言仍可正常工作。

## 排查

### 创建任务提示“不在白名单”

检查：

1. `whitelist.enabled`
2. `whitelist.allowed_users`
3. `whitelist.allowed_groups`
4. `whitelist.allowed_private_users`
5. 当前用户是否在 `permissions.super_admins`

### 创建群任务提示“没有跨聊天流创建任务权限”

如果用户在私聊里创建群任务，这属于跨聊天流创建。可选择：

1. 由 `super_admins` 创建。
2. 开启 `allow_cross_stream_by_default`。
3. 让用户在目标群聊中直接创建任务。

### 联网摘要没有联网事实

检查：

1. `tavily.enabled`
2. `tavily.api_key`
3. `tavily.endpoint`
4. 当前网络是否可访问 Tavily。

### 自动主动发起不触发

检查：

1. `targets` 是否配置目标。
2. `enabled_sources` 是否为空。
3. `frequency.global_frequency`、目标 `frequency` 和来源频率是否为 0。
4. 是否处于 `block_auto` 安静时段。
5. 是否达到 `max_auto_runs_per_day`。
6. LLM 判断是否返回 `should_speak=false`。

### 日程主动任务没有发言

检查：

1. `ctx.maisaka.trigger_proactive` 是否成功。
2. `proactive.maisaka_wait_seconds` 是否过短。
3. `proactive.fallback_enabled` 是否启用。
4. 父项目 `utils` 模型任务是否可用。
