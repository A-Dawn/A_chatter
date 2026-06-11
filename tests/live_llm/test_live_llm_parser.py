"""真实 LLM 解析套件。

默认跳过，设置 A_CHATTER_LIVE_LLM=1 后才会通过父项目 LLM capability 真实调用模型。
"""

from datetime import datetime
from typing import Any, Dict

import os
import pytest

from maibot_sdk.context import PluginContext

from src.plugin_runtime.integration import PluginRuntimeManager

from a_chatter.config import AChatterConfig
from a_chatter.models import ConfirmationDecision, ScheduleKind, TaskType
from a_chatter.parser import NaturalLanguageTaskParser, TaskNeedsClarification, build_parse_context
from a_chatter.service import AChatterService
from a_chatter.utils import utc_now


pytestmark = pytest.mark.live_llm


async def _host_capability_rpc(method: str, plugin_id: str, payload: Dict[str, Any] | None = None, timeout_ms: int | None = None) -> Any:
    """最小 Host RPC：通过父项目 PluginRuntimeManager 调用真实 capability。"""

    del timeout_ms
    if method != "cap.call":
        raise AssertionError(f"live_llm 测试只允许 cap.call，收到：{method}")
    if not isinstance(payload, dict):
        raise AssertionError("cap.call payload 必须是字典")
    capability = str(payload.get("capability") or "")
    args = payload.get("args")
    if not isinstance(args, dict):
        raise AssertionError("cap.call args 必须是字典")
    manager = PluginRuntimeManager()
    if capability == "llm.generate":
        result = await manager._cap_llm_generate(plugin_id, capability, args)
        if isinstance(result, dict) and result.get("success") is False:
            error = str(result.get("error") or "")
            if "Incorrect API key" in error or "invalid_api_key" in error or "401" in error:
                raise AssertionError("父项目 LLM capability 调用失败：模型配置/API Key 无效，未获得可分析输出")
            raise AssertionError(f"父项目 LLM capability 调用失败：{error or '未知错误'}")
        return result
    raise AssertionError(f"live_llm 测试未开放 capability：{capability}")


def _build_plugin_context() -> PluginContext:
    """构造使用父项目 capability 的 PluginContext。"""

    return PluginContext("github.A-Dawn.a-chatter", rpc_call=_host_capability_rpc)


def _require_live_llm() -> None:
    if os.environ.get("A_CHATTER_LIVE_LLM") != "1":
        pytest.skip("设置 A_CHATTER_LIVE_LLM=1 后才运行父项目真实 LLM 测试")


def _assert_draft_matches_plan(draft: Any) -> None:
    """分析真实 LLM 输出是否符合 A_chatter 计划架构。"""

    assert draft.task_type in {
        TaskType.REMINDER,
        TaskType.SCHEDULE_PROACTIVE,
        TaskType.AUTO_PROACTIVE,
        TaskType.RESEARCH_DIGEST,
    }
    assert draft.title.strip()
    assert draft.target.platform == "qq"
    assert draft.target.chat_type in {"private", "group"}
    assert draft.target.stream_id == "qq-private-10000"
    assert draft.schedule.kind == ScheduleKind.ONCE
    assert isinstance(draft.schedule.run_at, datetime)
    assert draft.schedule.run_at.tzinfo is not None
    assert draft.schedule.run_at > utc_now()
    assert draft.content.user_intent.strip()
    assert draft.confidence >= 0.7
    assert draft.ambiguities == []


def _assert_future_absolute_time(draft: Any) -> None:
    assert isinstance(draft.schedule.run_at, datetime)
    assert draft.schedule.run_at.tzinfo is not None
    assert draft.schedule.run_at > utc_now()


def _assert_confirmation_text(confirmation_text: str) -> None:
    assert "/ac 确认" in confirmation_text
    assert "/ac 取消" in confirmation_text
    assert "确认" in confirmation_text
    assert "取消" in confirmation_text


def _print_draft_analysis(case_name: str, draft: Any, confirmation_text: str) -> None:
    """打印不含密钥的真实 LLM 输出分析。"""

    print(f"[A_chatter live_llm] case={case_name}")
    print(f"task_type={draft.task_type.value}")
    print(f"title={draft.title}")
    print(f"target={draft.target.key}")
    print(f"target_stream_id={draft.target.stream_id}")
    print(f"schedule_kind={draft.schedule.kind.value}")
    print(f"run_at={draft.schedule.run_at.isoformat() if draft.schedule.run_at else ''}")
    print(f"confidence={draft.confidence}")
    print(f"ambiguities={draft.ambiguities}")
    print(f"must_say={draft.content.must_say}")
    print(f"requires_web={draft.content.requires_web}")
    print(f"confirmation_has_second_step={'/ac 确认' in confirmation_text and '/ac 取消' in confirmation_text}")
    print(f"confirmation_preview={confirmation_text[:160]}")


async def _parse_live(text: str, raw_context: Dict[str, str] | None = None) -> tuple[Any, str]:
    context = build_parse_context(
        raw_context
        or {
            "platform": "qq",
            "user_id": "10000",
            "stream_id": "qq-private-10000",
        }
    )
    parser = NaturalLanguageTaskParser(_build_plugin_context())
    draft = await parser.parse(text, context)
    confirmation_text = await parser.build_confirmation_text(draft)
    return draft, confirmation_text


@pytest.mark.asyncio
async def test_live_llm_parse_reminder_matches_plan() -> None:
    """真实 LLM 应把提醒需求解析成可二次确认的结构化草稿。"""

    _require_live_llm()
    draft, confirmation_text = await _parse_live("明天晚上八点提醒我交报告")

    _assert_draft_matches_plan(draft)
    _print_draft_analysis("parser.parse", draft, confirmation_text)
    _assert_confirmation_text(confirmation_text)
    assert draft.content.must_say is True


@pytest.mark.asyncio
async def test_live_llm_parse_schedule_proactive_matches_plan() -> None:
    """真实 LLM 应把到点自然发言需求解析为日程主动任务。"""

    _require_live_llm()
    draft, confirmation_text = await _parse_live(
        "明天上午九点问问大家今天项目进度怎么样",
        {
            "platform": "qq",
            "user_id": "10000",
            "group_id": "123456",
            "stream_id": "qq-group-123456",
        },
    )

    _print_draft_analysis("schedule_proactive", draft, confirmation_text)
    assert draft.task_type == TaskType.SCHEDULE_PROACTIVE
    assert draft.target.chat_type == "group"
    assert draft.target.stream_id == "qq-group-123456"
    assert draft.schedule.kind == ScheduleKind.ONCE
    _assert_future_absolute_time(draft)
    assert draft.content.must_say is True
    assert draft.content.requires_web is False
    _assert_confirmation_text(confirmation_text)


@pytest.mark.asyncio
async def test_live_llm_parse_research_digest_matches_plan() -> None:
    """真实 LLM 应把定期联网摘要需求解析为联网摘要或自动主动任务。"""

    _require_live_llm()
    draft, confirmation_text = await _parse_live("每天早上八点整理 AI 新闻摘要提醒我看")

    _print_draft_analysis("research_digest", draft, confirmation_text)
    assert draft.task_type in {TaskType.RESEARCH_DIGEST, TaskType.AUTO_PROACTIVE}
    assert draft.schedule.kind in {ScheduleKind.CRON, ScheduleKind.INTERVAL}
    if draft.schedule.kind == ScheduleKind.CRON:
        assert draft.schedule.cron.strip()
    if draft.schedule.kind == ScheduleKind.INTERVAL:
        assert draft.schedule.interval_seconds > 0
    assert draft.content.requires_web is True or draft.content.web_query.strip()
    _assert_confirmation_text(confirmation_text)


@pytest.mark.asyncio
async def test_live_llm_ambiguous_time_requires_clarification() -> None:
    """真实 LLM 遇到明显模糊时间时应触发追问，不保存草稿。"""

    _require_live_llm()
    with pytest.raises(TaskNeedsClarification) as exc_info:
        await _parse_live("晚上提醒我一下")

    print(f"[A_chatter live_llm] case=ambiguous_time clarification={exc_info.value}")
    assert exc_info.value.ambiguities


@pytest.mark.asyncio
async def test_live_llm_service_create_draft_uses_host_capability(tmp_path) -> None:
    """共享服务创建草稿时应通过父项目 LLM capability，而不是直连外部 SDK。"""

    _require_live_llm()
    config = AChatterConfig()
    service = AChatterService(_build_plugin_context(), config, tmp_path)
    await service.start()

    draft, confirmation_text = await service.create_draft(
        "明天晚上八点提醒我交报告",
        {"platform": "qq", "user_id": "10000", "stream_id": "qq-private-10000"},
    )

    _assert_draft_matches_plan(draft)
    _print_draft_analysis("service.create_draft", draft, confirmation_text)
    _assert_confirmation_text(confirmation_text)


@pytest.mark.asyncio
async def test_live_llm_natural_confirmation_reply_matches_plan(tmp_path) -> None:
    """真实 LLM 应能把非字面自然回复识别为确认或取消。"""

    _require_live_llm()
    config = AChatterConfig()
    service = AChatterService(_build_plugin_context(), config, tmp_path)
    await service.start()

    draft, confirmation_text = await service.create_draft(
        "明天晚上八点提醒我交报告",
        {"platform": "qq", "user_id": "10000", "stream_id": "qq-private-10000"},
    )
    handled, response, intent = await service.handle_natural_confirmation_reply(
        "这版可以，就按这个安排吧",
        {"platform": "qq", "user_id": "10000", "stream_id": "qq-private-10000"},
    )

    _print_draft_analysis("natural_confirmation", draft, confirmation_text)
    print(f"[A_chatter live_llm] natural_confirmation_decision={intent.decision.value}")
    print(f"[A_chatter live_llm] natural_confirmation_confidence={intent.confidence}")
    print(f"[A_chatter live_llm] natural_confirmation_response={response}")
    assert handled is True
    assert intent.decision == ConfirmationDecision.CONFIRM
    assert intent.confidence >= 0.7
    assert "已创建任务" in response
