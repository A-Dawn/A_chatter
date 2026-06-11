"""自然语言任务解析与确认文案生成。"""

from dataclasses import dataclass
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import json
import re

from .models import Actor, ChatTarget, ScheduleKind, ScheduleSpec, TaskContent, TaskDraft, TaskType
from .utils import default_target_from_context, extract_llm_response, parse_datetime, utc_now


class TaskParseError(ValueError):
    """任务解析失败。"""


class TaskNeedsClarification(TaskParseError):
    """任务需要用户补充信息。"""

    def __init__(self, message: str, ambiguities: List[str]) -> None:
        super().__init__(message)
        self.ambiguities = ambiguities


@dataclass(frozen=True)
class ParseContext:
    """解析上下文。"""

    actor: Actor
    source_stream_id: str
    current_target: ChatTarget
    timezone: str = "Asia/Shanghai"


class NaturalLanguageTaskParser:
    """使用 LLM 将自然语言请求解析为任务草稿。"""

    def __init__(self, ctx: Any, *, model_task: str = "utils") -> None:
        self._ctx = ctx
        self._model_task = model_task

    async def parse(self, text: str, context: ParseContext) -> TaskDraft:
        """解析自然语言任务。"""

        normalized_text = str(text or "").strip()
        if not normalized_text:
            raise TaskParseError("任务内容不能为空")

        prompt = self._build_parse_prompt(normalized_text, context)
        result = await self._ctx.llm.generate(prompt=prompt, model=self._model_task, temperature=0.1, max_tokens=2400)
        response_text = extract_llm_response(result)
        if isinstance(result, dict) and result.get("success") is False:
            raise TaskParseError(f"LLM 解析任务失败：{result.get('error') or response_text or '未知错误'}")
        payload = self._parse_json_response(response_text)
        return self._draft_from_payload(payload, context, normalized_text)

    async def build_confirmation_text(self, draft: TaskDraft) -> str:
        """生成二次确认文案。"""

        schedule_text = self._format_schedule(draft)
        target_text = draft.target.key if draft.target.stream_id else f"{draft.target.key}（未解析聊天流）"
        task_type_label = {
            TaskType.REMINDER: "硬提醒",
            TaskType.SCHEDULE_PROACTIVE: "日程主动发言",
            TaskType.AUTO_PROACTIVE: "自动主动发起",
            TaskType.RESEARCH_DIGEST: "联网摘要",
        }[draft.task_type]
        web_text = f"\n联网检索：{draft.content.web_query or '按任务内容生成'}" if draft.content.requires_web else ""
        return (
            "请确认是否创建以下 A_chatter 任务：\n"
            f"草稿 ID：{draft.draft_id}\n"
            f"标题：{draft.title}\n"
            f"类型：{task_type_label}\n"
            f"目标：{target_text}\n"
            f"时间：{schedule_text}\n"
            f"内容：{draft.content.user_intent}{web_text}\n"
            "确认请回复 `/ac 确认` 或 `/ac 确认 <草稿ID>`，取消请回复 `/ac 取消`。"
        )

    def _build_parse_prompt(self, text: str, context: ParseContext) -> str:
        now = utc_now().astimezone(ZoneInfo(context.timezone))
        current_target = context.current_target
        return f"""你是 MaiBot 插件 A_chatter 的任务解析器。请把用户需求解析为严格 JSON，不要输出解释文字。
最终回复必须只包含一个 JSON 对象，不能包含推理过程、自然语言解释、Markdown 代码块或 JSON 之外的任何字符。

当前时间：{now.isoformat()}
默认时区：{context.timezone}
当前用户：{context.actor.platform}:{context.actor.user_id}
当前聊天流：stream_id={context.source_stream_id}
当前默认目标：platform={current_target.platform}, chat_type={current_target.chat_type}, target_id={current_target.target_id}, stream_id={current_target.stream_id}

允许的 task_type：
- reminder：到点直接发送硬提醒
- schedule_proactive：到点触发 Maisaka 主动发言，必须产生发言
- auto_proactive：周期扫描后自动发起话题
- research_digest：按日程做联网摘要

允许的 schedule.kind：
- once：单次任务，必须给 run_at
- cron：周期任务，必须给 cron，并尽量给下次 run_at
- interval：间隔任务，必须给 interval_seconds，并尽量给下次 run_at

输出 JSON 格式：
{{
  "task_type": "reminder|schedule_proactive|auto_proactive|research_digest",
  "title": "简短标题",
  "target": {{
    "scope": "current|explicit",
    "platform": "{current_target.platform}",
    "chat_type": "group|private",
    "target_id": "",
    "stream_id": ""
  }},
  "schedule": {{
    "kind": "once|cron|interval",
    "timezone": "{context.timezone}",
    "run_at": "带时区 ISO 时间，例如 2026-06-11T20:00:00+08:00",
    "cron": "",
    "interval_seconds": 0
  }},
  "content": {{
    "user_intent": "到点实际执行的核心内容，不包含时间、目标和确认指令",
    "must_say": true,
    "requires_web": false,
    "web_query": "",
    "memory_query": "",
    "style_hint": "",
    "enabled_sources": []
  }},
  "safety": {{
    "needs_cross_stream_permission": false,
    "confidence": 0.0,
    "ambiguities": []
  }}
}}

约束：
1. 所有时间必须转为带时区的绝对 ISO 时间，不要输出“明天”“晚上”等相对表达。
2. confidence 低于 0.7 或 ambiguities 非空，表示需要追问，仍输出 JSON。
3. 如果用户没有指定目标，target.scope 使用 current。
4. reminder 的 content.user_intent 是到点发送的提醒正文，例如“明天晚上八点提醒我交报告”应写成“提醒我交报告”。
5. schedule_proactive 的 content.user_intent 是到点让 Maisaka 发言的核心意图，例如“问问大家今天项目进度怎么样”，不要重复时间条件。
6. 如果用户要求机器人到点自然聊、问大家、开话题，用 schedule_proactive。当前默认目标为群聊时，不要因为“大家”追问目标。
7. 如果用户要求每天/定期整理新闻、热点、资讯、论文等联网摘要，用 research_digest；即使末尾写“提醒我看”，也不要归为普通 reminder。
8. 如果用户要求每天/定期根据聊天历史、记忆或自省主动找话题，可以用 auto_proactive；仍要二次确认。
9. 如果时间缺少日期或具体钟点（如“晚上”“晚点”“明天提醒我”），必须把缺失项写入 ambiguities，不要自行默认补全。

用户需求：
{text}
"""

    def _parse_json_response(self, response_text: str) -> Dict[str, Any]:
        text = str(response_text or "").strip()
        if not text:
            raise TaskParseError("LLM 没有返回解析结果")
        fenced_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if fenced_match is not None:
            text = fenced_match.group(1).strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end < start:
                raise TaskParseError("LLM 返回内容不是 JSON 对象")
            text = text[start : end + 1]
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TaskParseError(f"LLM 返回 JSON 解析失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise TaskParseError("LLM 返回 JSON 必须是对象")
        return payload

    def _draft_from_payload(self, payload: Dict[str, Any], context: ParseContext, original_text: str) -> TaskDraft:
        safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
        confidence = float(safety.get("confidence") or 0.0)
        ambiguities = [str(item).strip() for item in safety.get("ambiguities", []) if str(item).strip()]
        if confidence < 0.7 or ambiguities:
            reason = "；".join(ambiguities) if ambiguities else "任务信息不够明确"
            raise TaskNeedsClarification(f"需要补充信息：{reason}", ambiguities)

        task_type = self._parse_task_type(payload.get("task_type"))
        target = self._parse_target(payload.get("target"), context)
        schedule = self._parse_schedule(payload.get("schedule"), task_type)
        content = self._parse_content(payload.get("content"), original_text, task_type)
        task_type = self._normalize_task_type(task_type, schedule, content, original_text)
        self._normalize_content(task_type, content)
        title = str(payload.get("title") or content.user_intent or "A_chatter 任务").strip()
        return TaskDraft(
            task_type=task_type,
            title=title[:80],
            target=target,
            schedule=schedule,
            content=content,
            confidence=confidence,
            ambiguities=[],
            creator_platform=context.actor.platform,
            creator_user_id=context.actor.user_id,
            source_stream_id=context.source_stream_id,
        )

    @classmethod
    def _normalize_task_type(
        cls,
        task_type: TaskType,
        schedule: ScheduleSpec,
        content: TaskContent,
        original_text: str,
    ) -> TaskType:
        """按计划架构修正 LLM 容易混淆的任务类型。"""

        if task_type == TaskType.REMINDER and cls._looks_like_research_digest(schedule, content, original_text):
            content.requires_web = True
            if not content.web_query:
                content.web_query = content.user_intent or original_text
            return TaskType.RESEARCH_DIGEST
        return task_type

    @staticmethod
    def _looks_like_research_digest(schedule: ScheduleSpec, content: TaskContent, original_text: str) -> bool:
        if schedule.kind not in {ScheduleKind.CRON, ScheduleKind.INTERVAL}:
            return False
        combined_text = f"{original_text} {content.user_intent} {content.web_query}".lower()
        digest_words = ("摘要", "简报", "整理", "汇总", "总结", "播报")
        web_words = ("新闻", "热点", "资讯", "快讯", "舆情", "日报", "周报", "论文", "ai", "openai", "模型")
        has_digest_action = any(word in combined_text for word in digest_words)
        has_web_signal = content.requires_web or bool(content.web_query) or any(word in combined_text for word in web_words)
        return has_digest_action and has_web_signal

    @classmethod
    def _normalize_content(cls, task_type: TaskType, content: TaskContent) -> None:
        if task_type == TaskType.REMINDER:
            content.user_intent = cls._strip_reminder_schedule_prefix(content.user_intent)

    @classmethod
    def _strip_reminder_schedule_prefix(cls, text: str) -> str:
        normalized_text = str(text or "").strip()
        match = re.match(r"^(?P<prefix>.+?)(?P<action>(?:请)?(?:提醒|叫|通知|喊)我.+)$", normalized_text)
        if match is None:
            return normalized_text
        prefix = match.group("prefix").strip(" ，,、")
        action = match.group("action").strip()
        if cls._is_schedule_only_prefix(prefix):
            return action
        return normalized_text

    @staticmethod
    def _is_schedule_only_prefix(text: str) -> bool:
        remainder = re.sub(
            r"(?:请|麻烦|帮我|在|于|到|等到|今天|明天|后天|大后天|每天|每日|每周|每月|每年|"
            r"今晚|明早|明晚|今早|早上|上午|中午|下午|晚上|凌晨|傍晚|周|星期|礼拜|"
            r"点|时|分|半|整|号|日|月|年|天|[0-9零一二两三四五六七八九十百:：/\-\s,，、]+)",
            "",
            text,
        )
        return not remainder.strip()

    @staticmethod
    def _parse_task_type(value: Any) -> TaskType:
        try:
            return TaskType(str(value or "").strip())
        except ValueError as exc:
            raise TaskParseError(f"不支持的任务类型：{value}") from exc

    @staticmethod
    def _parse_target(raw_target: Any, context: ParseContext) -> ChatTarget:
        if not isinstance(raw_target, dict):
            return context.current_target
        scope = str(raw_target.get("scope") or "current").strip()
        if scope == "current":
            return context.current_target
        platform = str(raw_target.get("platform") or context.current_target.platform).strip().lower()
        chat_type = str(raw_target.get("chat_type") or "").strip()
        target_id = str(raw_target.get("target_id") or "").strip()
        stream_id = str(raw_target.get("stream_id") or "").strip()
        if chat_type not in {"group", "private"} or not target_id:
            raise TaskParseError("显式目标必须包含 chat_type 和 target_id")
        return ChatTarget(platform=platform, chat_type=chat_type, target_id=target_id, stream_id=stream_id)

    @staticmethod
    def _parse_schedule(raw_schedule: Any, task_type: TaskType) -> ScheduleSpec:
        if not isinstance(raw_schedule, dict):
            raise TaskParseError("缺少日程信息")
        try:
            kind = ScheduleKind(str(raw_schedule.get("kind") or "").strip())
        except ValueError as exc:
            raise TaskParseError(f"不支持的日程类型：{raw_schedule.get('kind')}") from exc
        timezone_name = str(raw_schedule.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
        run_at = parse_datetime(raw_schedule.get("run_at"))
        cron = str(raw_schedule.get("cron") or "").strip()
        interval_seconds = int(raw_schedule.get("interval_seconds") or 0)
        if kind == ScheduleKind.ONCE and run_at is None:
            raise TaskParseError("单次任务必须包含 run_at")
        if kind == ScheduleKind.CRON and not cron:
            raise TaskParseError("cron 任务必须包含 cron 表达式")
        if kind == ScheduleKind.INTERVAL and interval_seconds <= 0:
            raise TaskParseError("interval 任务必须包含正数 interval_seconds")
        if task_type == TaskType.AUTO_PROACTIVE and kind == ScheduleKind.ONCE:
            raise TaskParseError("自动主动发起任务需要 cron 或 interval 日程")
        return ScheduleSpec(kind=kind, timezone=timezone_name, run_at=run_at, cron=cron, interval_seconds=interval_seconds)

    @staticmethod
    def _parse_content(raw_content: Any, original_text: str, task_type: TaskType) -> TaskContent:
        content = raw_content if isinstance(raw_content, dict) else {}
        enabled_sources = [str(item).strip() for item in content.get("enabled_sources", []) if str(item).strip()]
        if not enabled_sources and task_type == TaskType.AUTO_PROACTIVE:
            enabled_sources = ["history", "memory", "self_reflection"]
        return TaskContent(
            user_intent=str(content.get("user_intent") or original_text).strip(),
            must_say=bool(content.get("must_say", task_type in {TaskType.REMINDER, TaskType.SCHEDULE_PROACTIVE})),
            requires_web=bool(content.get("requires_web", task_type == TaskType.RESEARCH_DIGEST)),
            web_query=str(content.get("web_query") or "").strip(),
            memory_query=str(content.get("memory_query") or "").strip(),
            style_hint=str(content.get("style_hint") or "").strip(),
            enabled_sources=enabled_sources,
        )

    @staticmethod
    def _format_schedule(draft: TaskDraft) -> str:
        if draft.schedule.kind == ScheduleKind.ONCE:
            return draft.schedule.run_at.isoformat() if draft.schedule.run_at else "未设置"
        if draft.schedule.kind == ScheduleKind.CRON:
            return f"cron: {draft.schedule.cron}"
        return f"每 {draft.schedule.interval_seconds} 秒"


def build_parse_context(raw_context: Dict[str, Any]) -> ParseContext:
    """从 SDK 上下文字段构造解析上下文。"""

    from .utils import build_actor

    actor = build_actor(raw_context)
    current_target = default_target_from_context(raw_context)
    return ParseContext(actor=actor, source_stream_id=actor.stream_id, current_target=current_target)
