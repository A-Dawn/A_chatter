"""A_chatter 存储测试。"""

from datetime import timedelta

import pytest

from a_chatter.models import ChatTarget, ScheduleKind, ScheduleSpec, TaskContent, TaskDraft, TaskStatus, TaskType
from a_chatter.storage import AChatterStorage
from a_chatter.utils import make_id, utc_now


@pytest.mark.asyncio
async def test_pending_confirmation_can_be_saved_and_confirmed(tmp_path) -> None:
    storage = AChatterStorage(tmp_path / "a_chatter.sqlite3")
    await storage.initialize()
    now = utc_now()
    draft = TaskDraft(
        task_type=TaskType.REMINDER,
        title="交报告",
        target=ChatTarget(platform="qq", chat_type="private", target_id="10000", stream_id="stream_a"),
        schedule=ScheduleSpec(kind=ScheduleKind.ONCE, run_at=now + timedelta(hours=1)),
        content=TaskContent(user_intent="提醒我交报告", must_say=True),
        confidence=0.9,
        draft_id=make_id("draft"),
        creator_platform="qq",
        creator_user_id="10000",
        source_stream_id="stream_a",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    await storage.save_pending(draft, max_pending_per_user=3)
    loaded = await storage.get_pending_for_actor("qq", "10000", draft.draft_id)
    assert loaded is not None
    assert loaded.title == "交报告"

    task = await storage.create_task_from_draft(loaded)
    assert task.status == TaskStatus.ACTIVE
    assert task.next_run_at is not None
    assert await storage.get_pending_for_actor("qq", "10000", draft.draft_id) is None

    due_tasks = await storage.list_due_tasks(now + timedelta(hours=2))
    assert [item.task_id for item in due_tasks] == [task.task_id]

