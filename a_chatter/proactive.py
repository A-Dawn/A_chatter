"""Maisaka 主动触发与日程兜底执行器。"""

from datetime import datetime, timezone
from typing import Any

import asyncio

from .config import AChatterConfig
from .models import AChatterTask, ContextBundle, RunStatus, TaskRunResult
from .utils import extract_llm_response


class ProactiveExecutor:
    """执行 append_context、trigger_proactive 和必要兜底。"""

    def __init__(self, ctx: Any, config: AChatterConfig) -> None:
        self._ctx = ctx
        self._config = config

    def update_config(self, config: AChatterConfig) -> None:
        """更新配置引用。"""

        self._config = config

    async def trigger_schedule(self, task: AChatterTask, bundle: ContextBundle) -> TaskRunResult:
        """触发日程主动任务，必要时执行兜底。"""

        started_at = datetime.now(timezone.utc)
        append_result = await self._append_context(task.target.stream_id, bundle)
        if isinstance(append_result, dict) and append_result.get("success") is False:
            return TaskRunResult(False, RunStatus.FAILED, error=str(append_result.get("error") or "append_context 失败"))

        trigger_result = await self._ctx.maisaka.trigger_proactive(
            task.target.stream_id,
            bundle.intent,
            reason=bundle.reason,
            priority="high",
            metadata=bundle.metadata,
        )
        if isinstance(trigger_result, dict) and trigger_result.get("success") is False:
            if task.content.must_say and self._config.proactive.fallback_enabled:
                return await self._send_fallback(task, bundle, f"Maisaka 主动任务触发失败：{trigger_result.get('error')}")
            return TaskRunResult(False, RunStatus.FAILED, error=str(trigger_result.get("error") or "trigger_proactive 失败"))

        wait_seconds = max(0, int(self._config.proactive.maisaka_wait_seconds))
        if task.content.must_say and wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
            if await self._has_bot_message_after(task.target.stream_id, started_at):
                return TaskRunResult(True, RunStatus.SUCCESS, metadata={"trigger_result": trigger_result})
            if self._config.proactive.fallback_enabled:
                return await self._send_fallback(task, bundle, "等待后未观察到明确的 Bot 发言")

        return TaskRunResult(True, RunStatus.SUCCESS, metadata={"trigger_result": trigger_result})

    async def trigger_auto(self, target_stream_id: str, bundle: ContextBundle) -> TaskRunResult:
        """触发自动主动发起，不做兜底。"""

        append_result = await self._append_context(target_stream_id, bundle)
        if isinstance(append_result, dict) and append_result.get("success") is False:
            return TaskRunResult(False, RunStatus.FAILED, error=str(append_result.get("error") or "append_context 失败"))
        trigger_result = await self._ctx.maisaka.trigger_proactive(
            target_stream_id,
            bundle.intent,
            reason=bundle.reason,
            priority="normal",
            metadata=bundle.metadata,
        )
        if isinstance(trigger_result, dict) and trigger_result.get("success") is False:
            return TaskRunResult(False, RunStatus.FAILED, error=str(trigger_result.get("error") or "trigger_proactive 失败"))
        return TaskRunResult(True, RunStatus.SUCCESS, metadata={"trigger_result": trigger_result})

    async def _append_context(self, stream_id: str, bundle: ContextBundle) -> Any:
        return await self._ctx.maisaka.append_context(
            stream_id,
            [{"type": "text", "content": bundle.visible_text}],
            visible_text=bundle.visible_text,
            source_kind="plugin:a-chatter",
            message_id=f"a-chatter:{bundle.metadata.get('task_id') or bundle.metadata.get('source') or 'auto'}",
        )

    async def _has_bot_message_after(self, stream_id: str, started_at: datetime) -> bool:
        recent = await self._ctx.message.get_recent(stream_id, limit=20)
        messages = recent.get("messages") if isinstance(recent, dict) else recent
        if not isinstance(messages, list):
            return False
        for message in messages:
            if not isinstance(message, dict):
                continue
            timestamp = self._extract_timestamp(message)
            if timestamp is None or timestamp <= started_at:
                continue
            if self._is_bot_message(message):
                return True
        return False

    async def _send_fallback(self, task: AChatterTask, bundle: ContextBundle, reason: str) -> TaskRunResult:
        prompt = (
            "你是 MaiBot 的发言兜底生成器。下面是一个已经到点且必须发言的日程任务。\n"
            "请生成一条简短、自然、符合聊天语境的中文消息。\n"
            "不要提到插件、调度器、兜底、系统失败等内部信息。\n\n"
            f"任务标题：{task.title}\n"
            f"用户意图：{task.content.user_intent}\n"
            f"上下文：\n{bundle.visible_text[:4000]}"
        )
        result = await self._ctx.llm.generate(
            prompt=prompt,
            model=self._config.proactive.fallback_model_task,
            temperature=0.4,
            max_tokens=self._config.proactive.fallback_max_tokens,
        )
        text = extract_llm_response(result).strip()
        if not text:
            return TaskRunResult(False, RunStatus.FAILED, error=f"{reason}；兜底 LLM 未生成文本")
        send_result = await self._ctx.send.text(
            text,
            task.target.stream_id,
            typing=True,
            storage_message=True,
            sync_to_maisaka_history=True,
            maisaka_source_kind="plugin:a-chatter:fallback",
        )
        if isinstance(send_result, dict) and send_result.get("success") is False:
            return TaskRunResult(False, RunStatus.FAILED, error=str(send_result.get("error") or "兜底发送失败"))
        if send_result is False:
            return TaskRunResult(False, RunStatus.FAILED, error="兜底发送失败")
        return TaskRunResult(True, RunStatus.SUCCESS, used_fallback=True, metadata={"fallback_reason": reason})

    @staticmethod
    def _is_bot_message(message: dict[str, Any]) -> bool:
        if bool(message.get("is_bot")) or bool(message.get("is_self")) or bool(message.get("from_bot")):
            return True
        sender = message.get("sender")
        if isinstance(sender, dict):
            return bool(sender.get("is_bot") or sender.get("is_self"))
        message_info = message.get("message_info")
        if isinstance(message_info, dict):
            return bool(message_info.get("is_bot") or message_info.get("is_self"))
        return False

    @staticmethod
    def _extract_timestamp(message: dict[str, Any]) -> datetime | None:
        raw_timestamp = message.get("timestamp") or message.get("time")
        if isinstance(raw_timestamp, datetime):
            if raw_timestamp.tzinfo is None:
                return raw_timestamp.replace(tzinfo=timezone.utc)
            return raw_timestamp.astimezone(timezone.utc)
        try:
            timestamp = float(raw_timestamp)
        except (TypeError, ValueError):
            return None
        if timestamp > 100000000000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)

