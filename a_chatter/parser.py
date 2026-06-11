"""自然语言任务解析与确认文案生成。"""

from dataclasses import dataclass
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import json
import re

from .models import (
    Actor,
    ChatTarget,
    ConfirmationDecision,
    ConfirmationIntent,
    ScheduleKind,
    ScheduleSpec,
    TaskContent,
    TaskDraft,
    TaskType,
)
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

        summary = self.build_confirmation_summary(draft)
        prompt = self._build_confirmation_prompt(summary)
        result = await self._ctx.llm.generate(prompt=prompt, model=self._model_task, temperature=0.6, max_tokens=600)
        response_text = extract_llm_response(result).strip()
        if isinstance(result, dict) and result.get("success") is False:
            raise TaskParseError(f"LLM 生成确认文案失败：{result.get('error') or response_text or '未知错误'}")
        if not response_text:
            raise TaskParseError("LLM 没有返回确认文案")
        return self._ensure_confirmation_actions(response_text, summary)

    async def classify_confirmation_reply(self, text: str, drafts: List[TaskDraft]) -> ConfirmationIntent:
        """识别用户自然语言回复是否是在确认或取消待确认草稿。"""

        normalized_text = str(text or "").strip()
        if not normalized_text or not drafts:
            return ConfirmationIntent(decision=ConfirmationDecision.UNKNOWN, confidence=0.0, reason="no_text_or_draft")

        rule_intent = self._classify_confirmation_reply_by_rule(normalized_text, drafts)
        if rule_intent.decision != ConfirmationDecision.UNKNOWN:
            return rule_intent

        prompt = self._build_confirmation_reply_prompt(normalized_text, drafts)
        result = await self._ctx.llm.generate(prompt=prompt, model=self._model_task, temperature=0.0, max_tokens=500)
        response_text = extract_llm_response(result)
        if isinstance(result, dict) and result.get("success") is False:
            raise TaskParseError(f"LLM 识别确认回复失败：{result.get('error') or response_text or '未知错误'}")
        payload = self._parse_json_response(response_text)
        return self._confirmation_intent_from_payload(payload, drafts)

    @classmethod
    def build_confirmation_summary(cls, draft: TaskDraft) -> Dict[str, str]:
        """构造确认文案和自然回复判定共用的草稿摘要。"""

        schedule_text = cls._format_schedule(draft)
        target_text = draft.target.key if draft.target.stream_id else f"{draft.target.key}（未解析聊天流）"
        task_type_label = {
            TaskType.REMINDER: "硬提醒",
            TaskType.SCHEDULE_PROACTIVE: "日程主动发言",
            TaskType.AUTO_PROACTIVE: "自动主动发起",
            TaskType.RESEARCH_DIGEST: "联网摘要",
        }[draft.task_type]
        return {
            "draft_id": draft.draft_id,
            "title": draft.title,
            "task_type": task_type_label,
            "target": target_text,
            "schedule": schedule_text,
            "content": draft.content.user_intent,
            "web_query": draft.content.web_query or "按任务内容生成" if draft.content.requires_web else "",
        }

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

    @staticmethod
    def _build_confirmation_prompt(summary: Dict[str, str]) -> str:
        web_line = f"\n联网检索：{summary['web_query']}" if summary["web_query"] else ""
        return f"""你是 MaiBot 插件 A_chatter 的确认消息润色器。请把任务草稿写成一段自然、简洁、中文的二次确认话术。

要求：
1. 保留所有关键信息：草稿 ID、标题、类型、目标、时间、内容。
2. 语气可以自然一点，但不要假装任务已经创建。
3. 必须明确告诉用户可以自然回复确认或取消，也可以用 /ac 确认、/ac 取消。
4. 不要输出 Markdown 表格，不要输出代码块，不要暴露 LLM 或内部解析流程。
5. 最终只输出用户可见消息。

草稿摘要：
草稿 ID：{summary["draft_id"]}
标题：{summary["title"]}
类型：{summary["task_type"]}
目标：{summary["target"]}
时间：{summary["schedule"]}
内容：{summary["content"]}{web_line}

用户可见确认消息：
"""

    @staticmethod
    def _ensure_confirmation_actions(text: str, summary: Dict[str, str]) -> str:
        """确保 LLM 文案保留精确草稿信息和可操作确认锚点。"""

        normalized_text = str(text or "").strip()
        draft_id = summary["draft_id"]
        summary_fragments = [
            summary["draft_id"],
            summary["title"],
            summary["task_type"],
            summary["target"],
            summary["schedule"],
            summary["content"],
            summary["web_query"],
        ]
        if not all(fragment in normalized_text for fragment in summary_fragments if fragment):
            lines = [
                "核对信息：",
                f"草稿 ID：{summary['draft_id']}",
                f"标题：{summary['title']}",
                f"类型：{summary['task_type']}",
                f"目标：{summary['target']}",
                f"时间：{summary['schedule']}",
                f"内容：{summary['content']}",
            ]
            if summary["web_query"]:
                lines.append(f"联网检索：{summary['web_query']}")
            exact_summary = "\n".join(lines)
            normalized_text = f"{normalized_text}\n\n{exact_summary}" if normalized_text else exact_summary

        required_fragments = ("/ac 确认", "/ac 取消", draft_id)
        if all(fragment in normalized_text for fragment in required_fragments):
            return normalized_text
        action_line = f"确认的话可以直接回复“确认/就这样”，也可以发 `/ac 确认 {draft_id}`；取消则回复“取消/算了”，或发 `/ac 取消 {draft_id}`。"
        return f"{normalized_text}\n{action_line}" if normalized_text else action_line

    @classmethod
    def _build_confirmation_reply_prompt(cls, text: str, drafts: List[TaskDraft]) -> str:
        draft_lines = []
        for draft in drafts:
            summary = cls.build_confirmation_summary(draft)
            draft_lines.append(
                json.dumps(
                    {
                        "draft_id": summary["draft_id"],
                        "title": summary["title"],
                        "type": summary["task_type"],
                        "target": summary["target"],
                        "schedule": summary["schedule"],
                        "content": summary["content"],
                    },
                    ensure_ascii=False,
                )
            )
        return f"""你是 A_chatter 的二次确认回复判定器。请判断用户是否在确认或取消待确认任务草稿。
最终回复必须只包含一个 JSON 对象，不能包含解释、Markdown 或 JSON 外字符。

允许的 decision：
- confirm：用户明确同意创建草稿，例如“确认”“可以”“就这样”“帮我设上”“没问题”
- cancel：用户明确取消或否定，例如“取消”“算了”“不要了”“先别建”
- unknown：用户没有明确表达确认/取消，或只是在闲聊、修改需求、提出问题

如果用户提到草稿 ID，请提取到 draft_id；否则留空。
多个草稿且用户没有指定草稿时，如果意图明确也输出 decision，但 draft_id 留空。

输出 JSON：
{{
  "decision": "confirm|cancel|unknown",
  "confidence": 0.0,
  "draft_id": "",
  "reason": "简短原因"
}}

待确认草稿：
{chr(10).join(draft_lines)}

用户回复：
{text}
"""

    @classmethod
    def _classify_confirmation_reply_by_rule(cls, text: str, drafts: List[TaskDraft]) -> ConfirmationIntent:
        normalized_text = str(text or "").strip()
        draft_id = cls._extract_draft_id_from_text(normalized_text, drafts)
        compact = re.sub(r"\s+", "", normalized_text).lower()
        if not compact:
            return ConfirmationIntent(decision=ConfirmationDecision.UNKNOWN, reason="empty")

        confirm_phrases = {
            "确认",
            "确定",
            "可以",
            "好",
            "好的",
            "行",
            "没问题",
            "就这样",
            "就这个",
            "帮我设上",
            "帮我创建",
            "创建吧",
            "设上吧",
            "ok",
            "okay",
            "yes",
            "y",
        }
        cancel_phrases = {
            "取消",
            "算了",
            "不要",
            "不要了",
            "别建",
            "先别",
            "先别建",
            "撤销",
            "作废",
            "不用了",
            "no",
            "n",
        }
        if compact in confirm_phrases:
            return ConfirmationIntent(
                decision=ConfirmationDecision.CONFIRM,
                confidence=0.95,
                draft_id=draft_id,
                reason="rule_confirm_exact",
            )
        if compact in cancel_phrases:
            return ConfirmationIntent(
                decision=ConfirmationDecision.CANCEL,
                confidence=0.95,
                draft_id=draft_id,
                reason="rule_cancel_exact",
            )

        if any(phrase in compact for phrase in ("就这样", "就这个", "帮我设上", "创建吧", "设上吧")):
            return ConfirmationIntent(
                decision=ConfirmationDecision.CONFIRM,
                confidence=0.86,
                draft_id=draft_id,
                reason="rule_confirm_phrase",
            )
        if any(phrase in compact for phrase in ("取消", "算了", "不要了", "别建", "先别建", "作废")):
            return ConfirmationIntent(
                decision=ConfirmationDecision.CANCEL,
                confidence=0.86,
                draft_id=draft_id,
                reason="rule_cancel_phrase",
            )
        return ConfirmationIntent(decision=ConfirmationDecision.UNKNOWN, confidence=0.0, draft_id=draft_id)

    @staticmethod
    def _extract_draft_id_from_text(text: str, drafts: List[TaskDraft]) -> str:
        for draft in drafts:
            if draft.draft_id and draft.draft_id in text:
                return draft.draft_id
        match = re.search(r"\bdraft[_-][0-9A-Za-z_-]+\b", text)
        return match.group(0) if match is not None else ""

    @classmethod
    def _confirmation_intent_from_payload(cls, payload: Dict[str, Any], drafts: List[TaskDraft]) -> ConfirmationIntent:
        raw_decision = str(payload.get("decision") or "").strip().lower()
        try:
            decision = ConfirmationDecision(raw_decision)
        except ValueError:
            decision = ConfirmationDecision.UNKNOWN

        confidence = float(payload.get("confidence") or 0.0)
        draft_id = str(payload.get("draft_id") or "").strip()
        valid_draft_ids = {draft.draft_id for draft in drafts if draft.draft_id}
        if draft_id and draft_id not in valid_draft_ids:
            decision = ConfirmationDecision.UNKNOWN
            confidence = 0.0
        if confidence < 0.7:
            decision = ConfirmationDecision.UNKNOWN
        return ConfirmationIntent(
            decision=decision,
            confidence=confidence,
            draft_id=draft_id,
            reason=str(payload.get("reason") or "").strip(),
        )

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
