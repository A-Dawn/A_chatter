# A_chatter 代码规范

中文名：进阶闲谈家

本文档约束 A_chatter 插件实现的代码风格。产品计划见 `../../PLAN.md`，技术设计见 `TECHNICAL_DESIGN.md`，消息流转见 `MESSAGE_FLOW.md`。

## 基本原则

1. 代码以可读、可维护、可测试为第一优先级。
2. 插件只通过 `maibot_sdk` 能力访问宿主，不直接导入主程序 `src.*`。
3. 业务逻辑放在 `a_chatter/` 包内，`plugin.py` 只负责 SDK 注册和生命周期转发。
4. 不静默吞错，不用宽泛 fallback 掩盖问题；错误应进入日志、run 记录或用户可见响应。
5. 用户可见文本、日志和注释优先使用简体中文。
6. 不实现 WebUI，配置和管理走插件配置文件与聊天命令。

## 文件组织

建议保持以下职责边界：

1. `plugin.py`：插件入口、命令/工具注册、生命周期。
2. `config.py`：配置模型和默认值。
3. `models.py`：纯业务模型、枚举、dataclass 或 pydantic model。
4. `storage.py`：SQLite schema、migration、CRUD。
5. `scheduler.py`：后台调度循环和任务锁。
6. `parser.py`：LLM prompt、JSON 解析、草稿校验。
7. `rbac.py`：角色、权限和白名单判断。
8. `frequency.py`：频率密度函数和硬间隔判断。
9. `context_builder.py`：history、memory、web、subscription、persona context 组装。
10. `tavily_client.py`：Tavily HTTP 调用和响应归一化。
11. `proactive.py`：append context、trigger proactive、日程兜底。
12. `commands.py`：`/ac` 命令解析和响应。
13. `tools.py`：Maisaka Tool 入参解析和结构化返回。

单个模块不应无限膨胀。若文件开始同时承担多个清晰职责，应拆分服务类或辅助模块。

## 导入规范

1. 标准库和第三方库放在本地模块之前。
2. `from ... import ...` 放在 `import ...` 前。
3. 同一导入块内尽量按字母顺序排列，前提是不引入 import 错误。
4. 本地同目录模块优先使用相对导入。
5. 跨目录本地模块只允许导入插件包自身，例如 `from .models import ...` 或 `from a_chatter.models import ...`。
6. 不从 `src.*` 导入主程序内部模块。
7. 不在函数内部随意延迟导入，除非是为了打破真实循环依赖或隔离可选依赖。

示例：

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

import asyncio
import json
import sqlite3

from .models import AChatterTask, ChatTarget
from .storage import AChatterStorage
```

## 类型与模型

1. 复杂函数必须添加参数和返回值类型注解。
2. 参数超过 3 个、返回结构复杂、跨模块调用的函数必须有明确类型。
3. 参数化泛型使用 `typing` 中的 `List`、`Dict`、`Optional` 等形式，保持项目风格一致。
4. 外部输入先进入 pydantic model 或明确校验函数，再进入业务服务。
5. 枚举值使用稳定字符串，避免把展示文案作为存储值。
6. 时间一律使用带时区的 `datetime`，存储层统一转 UTC。

## 异步代码

1. SDK 能力调用、HTTP 请求、LLM 调用和调度器入口都使用 async。
2. 阻塞 SQLite 操作必须通过 `asyncio.to_thread` 包装，或使用声明过依赖的 async 数据库库。
3. 后台任务必须在 `on_unload` 中可取消、可等待、可清理。
4. 长耗时 LLM、Tavily 和存储操作必须设置超时或在调用层受调度器超时控制。
5. 不使用裸 `asyncio.create_task` 后丢弃引用，后台任务要保存句柄并集中管理。

## 错误处理

1. 不使用宽泛 `except Exception: pass`。
2. 捕获异常时必须记录错误原因，并根据场景写入 run 记录或返回用户可理解的错误。
3. 配置错误、权限错误、目标聊天流不存在、Tavily 未配置等应明确失败，不自动猜测 fallback。
4. LLM JSON 解析失败时返回用户可操作的提示，不保存草稿。
5. 日程驱动必须发言失败时才允许兜底发送；自动发起和 `self_reflection` 不兜底。
6. 兜底文本不得暴露插件、调度器、系统失败等内部信息。

## 日志与审计

1. 使用 SDK 或插件默认 logger，不使用 `print`。
2. 日志语言使用简体中文。
3. 关键业务行为必须写 run/audit，不只写日志。
4. 不记录完整 API Key、用户隐私原文或过长 LLM prompt。
5. RBAC 拒绝、Tavily 失败、LLM 解析失败、Maisaka trigger 失败必须有结构化日志。

## 配置规范

1. 配置项集中定义在 `config.py`，禁止业务模块散落硬编码默认值。
2. 配置字段命名使用 snake_case。
3. `enabled_sources` 只允许 `history`、`memory`、`web`、`subscription`、`self_reflection`。
4. `persona_context_enabled` 不是 source 开关。
5. `self_reflection` 必须复用自动发起频率密度函数，不允许绕过全局频率、目标频率、硬间隔、安静时段和 RBAC。
6. 配置热更新只刷新运行时状态，不删除任务、不清空 pending confirmation。

## LLM 与 Prompt

1. LLM 输出 JSON 的场景必须做严格解析和字段校验。
2. Prompt 中必须注入当前时间、时区、目标聊天信息和必要上下文，不让模型自行猜时间。
3. 日程解析输出必须是带时区绝对时间。
4. 普通 source 的发起理由必须来自明确锚点，不能只靠 persona 凭空生成。
5. `self_reflection` 才允许使用 persona context 作为候选意图驱动。
6. 最终触发 Maisaka 前，所有主动发言都必须注入 persona context。
7. Tavily 摘要 prompt 只产出事实包，不生成最终聊天话术。

## 存储规范

1. 插件使用自有 SQLite，不写入主程序数据库迁移体系。
2. schema 版本写入 `meta` 表。
3. 所有写操作应在事务中完成。
4. 任务、草稿、run 记录使用稳定业务 ID。
5. pending confirmation 必须有过期时间，默认 5 分钟。
6. 不把自行计算的 session hash 写入数据库；目标归属必须来自 `ctx.chat.*` 解析出的真实聊天流。

## 权限与安全

1. 命令入口、Maisaka Tool 入口、后台调度入口共享同一套 RBAC 服务。
2. 跨聊天流操作必须显式校验权限。
3. 群聊任务默认比私聊更严格。
4. 自动主动发起只扫描配置启用且白名单允许的目标。
5. 当前插件不主动创建新聊天流；目标不存在时提示用户先让 bot 与目标建立会话。
6. 不在日志、run metadata 或工具返回中泄露 API Key。

## 测试规范

1. 纯函数优先单元测试，尤其是 `frequency.py`、`rbac.py`、`parser.py`、`storage.py`。
2. SDK 能力调用使用 fake ctx 或 mock。
3. 必测路径：
   - 创建草稿、确认、过期取消。
   - RBAC 拒绝。
   - 频率越高概率越高。
   - `min_interval_seconds` 硬间隔生效。
   - `self_reflection` 不绕过频率密度。
   - 日程触发 Maisaka。
   - 日程无发言后兜底。
   - 自动发起不兜底。
   - Tavily 未配置时联网 source 禁用。
4. 不为配置模板改动单独创建测试，除非配置解析逻辑本身有复杂行为。

## 代码审查清单

提交或交付前至少检查：

1. 是否直接导入了 `src.*`。
2. 是否绕过 `ctx.chat.*` 自行计算 session_id。
3. 是否有静默 fallback 或裸 `except`。
4. 是否所有用户可见错误都足够明确。
5. 是否所有后台任务都能停止。
6. 是否所有 source 都经过频率密度、RBAC 和白名单。
7. 是否 `persona_context` 没被误当作普通 source。
8. 是否 `self_reflection` 仍属于 `auto_proactive` 的 source，而不是独立执行链路。
9. 是否更新了 `_manifest.json` dependencies。
10. 是否补充了必要测试。
