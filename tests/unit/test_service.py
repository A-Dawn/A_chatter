"""A_chatter 业务服务测试。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from a_chatter.models import ScheduleKind, ScheduleSpec
from a_chatter.service import AChatterService


def test_compute_next_run_at_respects_cron_timezone(monkeypatch) -> None:
    now = datetime(2026, 7, 12, 23, 6, tzinfo=timezone.utc)
    monkeypatch.setattr("a_chatter.service.utc_now", lambda: now)
    service = object.__new__(AChatterService)

    cron_task = SimpleNamespace(
        schedule=ScheduleSpec(kind=ScheduleKind.CRON, timezone="Asia/Shanghai", cron="5 7 * * *")
    )
    assert service.compute_next_run_at(cron_task) == datetime(2026, 7, 13, 23, 5, tzinfo=timezone.utc)

    once_task = SimpleNamespace(schedule=ScheduleSpec(kind=ScheduleKind.ONCE))
    interval_task = SimpleNamespace(schedule=ScheduleSpec(kind=ScheduleKind.INTERVAL, interval_seconds=60))
    assert service.compute_next_run_at(once_task) is None
    assert service.compute_next_run_at(interval_task) == now + timedelta(seconds=60)
