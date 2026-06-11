"""A_chatter 功能流测试。"""

from datetime import timedelta
from pathlib import Path
from typing import List

import pytest

from a_chatter.commands import AChatterCommandService
from a_chatter.config import AChatterConfig, TargetConfig
from a_chatter.models import ChatTarget, ScheduleKind, ScheduleSpec, TaskContent, TaskDraft, TaskType
from a_chatter.service import AChatterService
from a_chatter.tools import AChatterToolService
from a_chatter.utils import make_id, utc_now

from tests.helpers import FakeContext, build_parse_response, default_sdk_context


async def _build_service(tmp_path: Path, llm_responses: List[str]) -> tuple[AChatterService, FakeContext]:
    config = AChatterConfig()
    config.proactive.maisaka_wait_seconds = 0
    context = FakeContext(llm_responses)
    service = AChatterService(context, config, tmp_path)
    await service.start()
    return service, context


def _explicit_group_parse_response(run_at: str) -> str:
    return build_parse_response(run_at).replace(
        '"scope": "current", "platform": "qq", "chat_type": "private", "target_id": "10000"',
        '"scope": "explicit", "platform": "qq", "chat_type": "group", "target_id": "123456", "stream_id": ""',
    )


@pytest.mark.asyncio
async def test_command_create_confirm_and_list_flow(tmp_path: Path) -> None:
    run_at = (utc_now() + timedelta(hours=1)).isoformat()
    service, context = await _build_service(tmp_path, [build_parse_response(run_at)])
    commands = AChatterCommandService(service)
    sdk_context = default_sdk_context()

    success, _, _ = await commands.handle("新增 明天晚上八点提醒我交报告", "qq-private-10000", sdk_context)
    assert success is True
    assert "请确认是否创建" in context.send.sent_texts[-1][1]

    success, _, _ = await commands.handle("确认", "qq-private-10000", sdk_context)
    assert success is True
    assert "已创建任务" in context.send.sent_texts[-1][1]

    success, _, _ = await commands.handle("列表 当前", "qq-private-10000", sdk_context)
    assert success is True
    assert "交报告提醒" in context.send.sent_texts[-1][1]


@pytest.mark.asyncio
async def test_tool_create_and_confirm_flow(tmp_path: Path) -> None:
    run_at = (utc_now() + timedelta(hours=1)).isoformat()
    service, _ = await _build_service(tmp_path, [build_parse_response(run_at)])
    tools = AChatterToolService(service)
    sdk_context = default_sdk_context()

    draft_result = await tools.create_task_draft("明天晚上八点提醒我交报告", sdk_context)

    assert draft_result["success"] is True
    assert draft_result["requires_user_confirmation"] is True
    assert draft_result["draft_id"]

    confirm_result = await tools.confirm_task("", sdk_context)

    assert confirm_result["success"] is True
    assert confirm_result["task_id"]
    assert "交报告提醒" in confirm_result["task_summary"]


@pytest.mark.asyncio
async def test_execute_reminder_sends_text(tmp_path: Path) -> None:
    service, context = await _build_service(tmp_path, [])
    now = utc_now()
    draft = TaskDraft(
        task_type=TaskType.REMINDER,
        title="交报告提醒",
        target=ChatTarget(platform="qq", chat_type="private", target_id="10000", stream_id="qq-private-10000"),
        schedule=ScheduleSpec(kind=ScheduleKind.ONCE, run_at=now),
        content=TaskContent(user_intent="提醒我交报告", must_say=True),
        confidence=0.9,
        draft_id=make_id("draft"),
        creator_platform="qq",
        creator_user_id="10000",
        source_stream_id="qq-private-10000",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    await service.storage.save_pending(draft, max_pending_per_user=3)
    task = await service.storage.create_task_from_draft(draft)

    await service.execute_task(task)

    assert context.send.sent_texts[-1] == ("qq-private-10000", "提醒我交报告")
    updated_task = await service.storage.get_task(task.task_id)
    assert updated_task is not None
    assert updated_task.next_run_at is None


@pytest.mark.asyncio
async def test_execute_schedule_proactive_appends_and_triggers(tmp_path: Path) -> None:
    service, context = await _build_service(tmp_path, [])
    now = utc_now()
    draft = TaskDraft(
        task_type=TaskType.SCHEDULE_PROACTIVE,
        title="项目进度问候",
        target=ChatTarget(platform="qq", chat_type="private", target_id="10000", stream_id="qq-private-10000"),
        schedule=ScheduleSpec(kind=ScheduleKind.ONCE, run_at=now),
        content=TaskContent(user_intent="问问项目进度", must_say=True, memory_query="项目进度"),
        confidence=0.9,
        draft_id=make_id("draft"),
        creator_platform="qq",
        creator_user_id="10000",
        source_stream_id="qq-private-10000",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    await service.storage.save_pending(draft, max_pending_per_user=3)
    task = await service.storage.create_task_from_draft(draft)

    await service.execute_task(task)

    assert context.maisaka.appended
    assert context.maisaka.triggered
    assert context.maisaka.triggered[-1]["stream_id"] == "qq-private-10000"
    assert "问问项目进度" in context.maisaka.triggered[-1]["intent"]


@pytest.mark.asyncio
async def test_cross_stream_group_requires_permission(tmp_path: Path) -> None:
    run_at = (utc_now() + timedelta(hours=1)).isoformat()
    service, _ = await _build_service(tmp_path, [_explicit_group_parse_response(run_at)])
    commands = AChatterCommandService(service)

    success, message, _ = await commands.handle("新增 明天九点在群里提醒开会", "qq-private-10000", default_sdk_context())

    assert success is False
    assert "跨聊天流" in message


@pytest.mark.asyncio
async def test_super_admin_can_create_cross_stream_group_task(tmp_path: Path) -> None:
    run_at = (utc_now() + timedelta(hours=1)).isoformat()
    config = AChatterConfig()
    config.permissions.super_admins = ["qq:10000"]
    context = FakeContext([_explicit_group_parse_response(run_at)])
    service = AChatterService(context, config, tmp_path)
    await service.start()
    commands = AChatterCommandService(service)

    success, confirmation_text, _ = await commands.handle(
        "新增 明天九点在群里提醒开会",
        "qq-private-10000",
        default_sdk_context(),
    )

    assert success is True
    assert "qq:group:123456" in confirmation_text
    drafts = await service.storage.list_pending_for_actor("qq", "10000")
    assert len(drafts) == 1
    assert drafts[0].target.stream_id == "qq-group-123456"


@pytest.mark.asyncio
async def test_schedule_proactive_quiet_hours_adds_style_context(tmp_path: Path) -> None:
    config = AChatterConfig()
    config.proactive.maisaka_wait_seconds = 0
    config.targets = [
        TargetConfig(
            target="qq:private:10000",
            quiet_hours_enabled=True,
            quiet_hours=["00:00-23:59"],
            quiet_mode="style_only",
        )
    ]
    context = FakeContext([])
    service = AChatterService(context, config, tmp_path)
    await service.start()
    now = utc_now()
    draft = TaskDraft(
        task_type=TaskType.SCHEDULE_PROACTIVE,
        title="安静时段问候",
        target=ChatTarget(platform="qq", chat_type="private", target_id="10000", stream_id="qq-private-10000"),
        schedule=ScheduleSpec(kind=ScheduleKind.ONCE, run_at=now),
        content=TaskContent(user_intent="问问项目进度", must_say=True),
        confidence=0.9,
        draft_id=make_id("draft"),
        creator_platform="qq",
        creator_user_id="10000",
        source_stream_id="qq-private-10000",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    await service.storage.save_pending(draft, max_pending_per_user=3)
    task = await service.storage.create_task_from_draft(draft)

    await service.execute_task(task)

    assert context.maisaka.appended
    visible_text = str(context.maisaka.appended[-1]["kwargs"].get("visible_text") or "")
    assert "[安静时段]" in visible_text
    assert "仍然需要发言" in visible_text
    assert context.maisaka.triggered
