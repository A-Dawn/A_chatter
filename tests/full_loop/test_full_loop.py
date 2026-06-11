"""A_chatter 完整循环测试。"""

from datetime import timedelta
from pathlib import Path

import json
import pytest

from a_chatter.commands import AChatterCommandService
from a_chatter.config import AChatterConfig, TargetConfig
from a_chatter.models import ScheduleKind, TaskStatus, TaskType
from a_chatter.scheduler import AChatterScheduler
from a_chatter.service import AChatterService
from a_chatter.tavily_client import TavilyResult
from a_chatter.utils import utc_now

from tests.helpers import FakeContext, build_confirmation_response, default_sdk_context


pytestmark = pytest.mark.full_loop


async def _build_service(tmp_path: Path, llm_responses: list[str]) -> tuple[AChatterService, FakeContext]:
    config = AChatterConfig()
    config.proactive.maisaka_wait_seconds = 0
    context = FakeContext(llm_responses)
    service = AChatterService(context, config, tmp_path)
    await service.start()
    return service, context


def _parse_response(
    *,
    task_type: TaskType,
    title: str,
    user_intent: str,
    run_at: str,
    schedule_kind: ScheduleKind = ScheduleKind.ONCE,
    cron: str = "",
    requires_web: bool = False,
    web_query: str = "",
    memory_query: str = "",
) -> str:
    return json.dumps(
        {
            "task_type": task_type.value,
            "title": title,
            "target": {"scope": "current", "platform": "qq", "chat_type": "private", "target_id": "10000"},
            "schedule": {
                "kind": schedule_kind.value,
                "timezone": "Asia/Shanghai",
                "run_at": run_at,
                "cron": cron,
                "interval_seconds": 0,
            },
            "content": {
                "user_intent": user_intent,
                "must_say": True,
                "requires_web": requires_web,
                "web_query": web_query,
                "memory_query": memory_query,
                "style_hint": "",
                "enabled_sources": [],
            },
            "safety": {"needs_cross_stream_permission": False, "confidence": 0.92, "ambiguities": []},
        },
        ensure_ascii=False,
    )


async def _create_and_confirm_due_task(
    service: AChatterService,
    context: FakeContext,
    user_request: str,
) -> str:
    commands = AChatterCommandService(service)
    sdk_context = default_sdk_context()

    success, confirmation_text, _ = await commands.handle(f"新增 {user_request}", "qq-private-10000", sdk_context)
    assert success is True
    assert "/ac 确认" in confirmation_text
    assert "/ac 取消" in confirmation_text

    success, created_text, _ = await commands.handle("确认", "qq-private-10000", sdk_context)
    assert success is True
    assert "已创建任务" in created_text

    tasks = await service.storage.list_tasks(target_stream_id="qq-private-10000")
    assert len(tasks) == 1
    assert tasks[0].next_run_at is not None
    assert tasks[0].next_run_at <= utc_now()
    assert context.send.sent_texts[-1][0] == "qq-private-10000"
    return tasks[0].task_id


@pytest.mark.asyncio
async def test_command_confirm_scheduler_reminder_full_loop(tmp_path: Path) -> None:
    """用户命令创建、确认、调度到期、最终发送硬提醒。"""

    run_at = (utc_now() - timedelta(seconds=1)).isoformat()
    service, context = await _build_service(
        tmp_path,
        [
            _parse_response(
                task_type=TaskType.REMINDER,
                title="交报告提醒",
                user_intent="提醒我交报告",
                run_at=run_at,
            ),
            build_confirmation_response(),
        ],
    )

    task_id = await _create_and_confirm_due_task(service, context, "现在提醒我交报告")
    await AChatterScheduler(service)._run_once()

    assert context.send.sent_texts[-1] == ("qq-private-10000", "提醒我交报告")
    updated_task = await service.storage.get_task(task_id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.COMPLETED
    assert updated_task.last_run_at is not None
    assert updated_task.next_run_at is None


@pytest.mark.asyncio
async def test_command_confirm_scheduler_schedule_proactive_full_loop(tmp_path: Path) -> None:
    """用户命令创建、确认、调度到期、最终触发 Maisaka 主动发言。"""

    run_at = (utc_now() - timedelta(seconds=1)).isoformat()
    service, context = await _build_service(
        tmp_path,
        [
            _parse_response(
                task_type=TaskType.SCHEDULE_PROACTIVE,
                title="项目进度询问",
                user_intent="问问大家今天项目进度怎么样",
                run_at=run_at,
                memory_query="项目进度",
            ),
            build_confirmation_response(),
        ],
    )

    task_id = await _create_and_confirm_due_task(service, context, "现在问问大家今天项目进度怎么样")
    await AChatterScheduler(service)._run_once()

    assert context.maisaka.appended
    assert context.maisaka.triggered
    assert context.maisaka.triggered[-1]["stream_id"] == "qq-private-10000"
    assert "问问大家今天项目进度怎么样" in context.maisaka.triggered[-1]["intent"]
    updated_task = await service.storage.get_task(task_id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_command_confirm_scheduler_research_digest_full_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """联网摘要任务到期后应压缩检索事实并注入 Maisaka。"""

    run_at = (utc_now() - timedelta(seconds=1)).isoformat()
    service, context = await _build_service(
        tmp_path,
        [
            _parse_response(
                task_type=TaskType.RESEARCH_DIGEST,
                title="AI 新闻摘要",
                user_intent="整理 AI 新闻摘要提醒我看",
                run_at=run_at,
                schedule_kind=ScheduleKind.CRON,
                cron="0 8 * * *",
                requires_web=True,
                web_query="AI 新闻摘要",
            ),
            build_confirmation_response(),
            "- OpenAI 发布新模型更新\n  来源：https://example.com/ai-news",
        ],
    )

    async def fake_search(query: str) -> list[TavilyResult]:
        assert query == "AI 新闻摘要"
        return [
            TavilyResult(
                title="OpenAI 发布新模型更新",
                url="https://example.com/ai-news",
                snippet="新模型在推理和响应速度上有更新。",
            )
        ]

    monkeypatch.setattr(service.tavily_client, "search", fake_search)

    task_id = await _create_and_confirm_due_task(service, context, "每天早上八点整理 AI 新闻摘要提醒我看")
    await AChatterScheduler(service)._run_once()

    assert context.maisaka.appended
    visible_text = str(context.maisaka.appended[-1]["kwargs"].get("visible_text") or "")
    assert "[联网检索事实包]" in visible_text
    assert "https://example.com/ai-news" in visible_text
    assert context.maisaka.triggered
    updated_task = await service.storage.get_task(task_id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.ACTIVE
    assert updated_task.next_run_at is not None
    assert updated_task.next_run_at > utc_now()


@pytest.mark.asyncio
async def test_auto_proactive_scan_triggers_maisaka_full_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """自动发起应经过目标扫描、LLM 判断、频率放行并触发 Maisaka。"""

    config = AChatterConfig()
    config.targets = [
        TargetConfig(
            target="qq:private:10000",
            enabled=True,
            enabled_sources=["history"],
            frequency=1.0,
            max_auto_runs_per_day=2,
        )
    ]
    config.frequency.min_interval_seconds = 0
    context = FakeContext(
        [
            json.dumps(
                {
                    "should_speak": True,
                    "intent_score": 1.0,
                    "reason": "最近在聊项目进度，可以自然接一下。",
                    "intent_kind": "history",
                    "topic": "项目进度",
                    "style_hint": "轻松询问",
                },
                ensure_ascii=False,
            )
        ]
    )
    service = AChatterService(context, config, tmp_path)
    await service.start()
    monkeypatch.setattr("a_chatter.service.random.random", lambda: 0.0)

    await service.scan_auto_targets()

    assert context.maisaka.appended
    assert context.maisaka.triggered
    assert context.maisaka.triggered[-1]["stream_id"] == "qq-private-10000"
    assert "项目进度" in context.maisaka.triggered[-1]["intent"]
    state = await service.storage.get_target_state("qq-private-10000")
    assert state.daily_auto_count == 1
    assert state.last_auto_run_at is not None


@pytest.mark.asyncio
async def test_auto_proactive_scan_records_skip_when_llm_rejects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """自动发起 LLM 判断不值得说时应记录跳过且不触发 Maisaka。"""

    config = AChatterConfig()
    config.targets = [TargetConfig(target="qq:private:10000", enabled=True, enabled_sources=["history"])]
    config.frequency.min_interval_seconds = 0
    context = FakeContext(
        [
            json.dumps(
                {
                    "should_speak": False,
                    "intent_score": 0.0,
                    "reason": "当前话题已经结束，不适合打扰。",
                    "intent_kind": "history",
                    "topic": "",
                    "style_hint": "",
                },
                ensure_ascii=False,
            )
        ]
    )
    service = AChatterService(context, config, tmp_path)
    await service.start()
    monkeypatch.setattr("a_chatter.service.random.random", lambda: 0.0)

    await service.scan_auto_targets()

    assert context.maisaka.triggered == []
    state = await service.storage.get_target_state("qq-private-10000")
    assert state.daily_auto_count == 0
