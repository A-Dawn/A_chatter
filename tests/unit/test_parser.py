"""自然语言任务解析单元测试。"""

from datetime import timedelta

import json
import pytest

from a_chatter.models import ConfirmationDecision, TaskType
from a_chatter.parser import NaturalLanguageTaskParser, build_parse_context
from a_chatter.utils import utc_now

from tests.helpers import FakeContext, build_confirmation_intent_response, build_confirmation_response, default_sdk_context


def _reminder_parse_response(run_at: str, user_intent: str = "提醒我交报告") -> str:
    return json.dumps(
        {
            "task_type": "reminder",
            "title": "交报告提醒",
            "target": {"scope": "current", "platform": "qq", "chat_type": "private", "target_id": "10000"},
            "schedule": {
                "kind": "once",
                "timezone": "Asia/Shanghai",
                "run_at": run_at,
                "cron": "",
                "interval_seconds": 0,
            },
            "content": {
                "user_intent": user_intent,
                "must_say": True,
                "requires_web": False,
                "web_query": "",
                "memory_query": "",
                "style_hint": "",
                "enabled_sources": [],
            },
            "safety": {"needs_cross_stream_permission": False, "confidence": 0.9, "ambiguities": []},
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_periodic_web_digest_is_normalized_from_reminder() -> None:
    """周期联网摘要即使被模型误分类为提醒，也应落入 research_digest。"""

    response = json.dumps(
        {
            "task_type": "reminder",
            "title": "AI 新闻摘要提醒",
            "target": {"scope": "current", "platform": "qq", "chat_type": "private", "target_id": "10000"},
            "schedule": {
                "kind": "cron",
                "timezone": "Asia/Shanghai",
                "run_at": (utc_now() + timedelta(days=1)).isoformat(),
                "cron": "0 8 * * *",
                "interval_seconds": 0,
            },
            "content": {
                "user_intent": "每天早上八点整理 AI 新闻摘要并提醒查看",
                "must_say": True,
                "requires_web": True,
                "web_query": "AI 新闻摘要",
                "memory_query": "",
                "style_hint": "",
                "enabled_sources": [],
            },
            "safety": {"needs_cross_stream_permission": False, "confidence": 0.9, "ambiguities": []},
        },
        ensure_ascii=False,
    )
    parser = NaturalLanguageTaskParser(FakeContext([response]))

    draft = await parser.parse("每天早上八点整理 AI 新闻摘要提醒我看", build_parse_context(default_sdk_context()))

    assert draft.task_type == TaskType.RESEARCH_DIGEST
    assert draft.content.requires_web is True
    assert draft.content.web_query == "AI 新闻摘要"


@pytest.mark.asyncio
async def test_reminder_content_strips_schedule_prefix() -> None:
    """硬提醒正文不应把调度时间再次发给用户。"""

    response = _reminder_parse_response(
        (utc_now() + timedelta(days=1)).isoformat(),
        user_intent="明天晚上八点提醒我交报告",
    )
    parser = NaturalLanguageTaskParser(FakeContext([response]))

    draft = await parser.parse("明天晚上八点提醒我交报告", build_parse_context(default_sdk_context()))

    assert draft.content.user_intent == "提醒我交报告"


@pytest.mark.asyncio
async def test_confirmation_text_is_llm_generated_and_keeps_action_anchors() -> None:
    """确认文案应来自 LLM，并保留稳定确认/取消锚点。"""

    run_at = (utc_now() + timedelta(days=1)).isoformat()
    context = FakeContext([build_confirmation_response("这事我先整理成一个草稿给你看。")])
    parser = NaturalLanguageTaskParser(context)
    draft = await NaturalLanguageTaskParser(FakeContext([_reminder_parse_response(run_at)])).parse(
        "明天晚上八点提醒我交报告",
        build_parse_context(default_sdk_context()),
    )

    confirmation_text = await parser.build_confirmation_text(draft)

    assert "这事我先整理成一个草稿给你看" in confirmation_text
    assert "/ac 确认" in confirmation_text
    assert "/ac 取消" in confirmation_text
    assert draft.draft_id in confirmation_text
    assert "确认消息润色器" in context.llm.prompts[0]


@pytest.mark.asyncio
async def test_confirmation_reply_classifier_uses_llm_for_non_literal_reply() -> None:
    """非字面确认回复应由 LLM 判定。"""

    run_at = (utc_now() + timedelta(days=1)).isoformat()
    draft = await NaturalLanguageTaskParser(
        FakeContext([_reminder_parse_response(run_at)])
    ).parse("明天晚上八点提醒我交报告", build_parse_context(default_sdk_context()))
    context = FakeContext([build_confirmation_intent_response("confirm")])
    parser = NaturalLanguageTaskParser(context)

    intent = await parser.classify_confirmation_reply("这版可以，按这个安排", [draft])

    assert intent.decision == ConfirmationDecision.CONFIRM
    assert "二次确认回复判定器" in context.llm.prompts[0]
