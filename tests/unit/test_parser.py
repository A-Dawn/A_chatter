"""自然语言任务解析单元测试。"""

from datetime import timedelta

import json
import pytest

from a_chatter.models import TaskType
from a_chatter.parser import NaturalLanguageTaskParser, build_parse_context
from a_chatter.utils import utc_now

from tests.helpers import FakeContext, default_sdk_context


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

    response = json.dumps(
        {
            "task_type": "reminder",
            "title": "交报告提醒",
            "target": {"scope": "current", "platform": "qq", "chat_type": "private", "target_id": "10000"},
            "schedule": {
                "kind": "once",
                "timezone": "Asia/Shanghai",
                "run_at": (utc_now() + timedelta(days=1)).isoformat(),
                "cron": "",
                "interval_seconds": 0,
            },
            "content": {
                "user_intent": "明天晚上八点提醒我交报告",
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
    parser = NaturalLanguageTaskParser(FakeContext([response]))

    draft = await parser.parse("明天晚上八点提醒我交报告", build_parse_context(default_sdk_context()))

    assert draft.content.user_intent == "提醒我交报告"
