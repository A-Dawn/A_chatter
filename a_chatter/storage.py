"""A_chatter SQLite 存储层。"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncio
import json
import sqlite3

from .models import AChatterTask, ChatTarget, ScheduleKind, ScheduleSpec, TargetState, TaskContent, TaskDraft, TaskStatus, TaskType
from .utils import from_json_dict, make_id, parse_datetime, to_utc_iso, utc_now


SCHEMA_VERSION = "1"


class AChatterStorage:
    """插件自有 SQLite 存储。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """初始化数据库 schema。"""

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._initialize_sync)

    async def save_pending(self, draft: TaskDraft, *, max_pending_per_user: int) -> None:
        """保存待确认草稿，并清理同用户超限草稿。"""

        async with self._write_lock:
            await asyncio.to_thread(self._save_pending_sync, draft, max_pending_per_user)

    async def get_pending_for_actor(
        self,
        creator_platform: str,
        creator_user_id: str,
        draft_id: str = "",
    ) -> Optional[TaskDraft]:
        """读取用户待确认草稿。未指定 draft_id 时只允许命中唯一草稿。"""

        return await asyncio.to_thread(self._get_pending_for_actor_sync, creator_platform, creator_user_id, draft_id)

    async def list_pending_for_actor(self, creator_platform: str, creator_user_id: str) -> List[TaskDraft]:
        """列出用户未过期草稿。"""

        return await asyncio.to_thread(self._list_pending_for_actor_sync, creator_platform, creator_user_id)

    async def delete_pending(self, draft_id: str) -> bool:
        """删除待确认草稿。"""

        async with self._write_lock:
            return await asyncio.to_thread(self._delete_pending_sync, draft_id)

    async def create_task_from_draft(self, draft: TaskDraft) -> AChatterTask:
        """确认草稿并创建正式任务。"""

        async with self._write_lock:
            return await asyncio.to_thread(self._create_task_from_draft_sync, draft)

    async def list_tasks(
        self,
        *,
        target_stream_id: str = "",
        creator_platform: str = "",
        creator_user_id: str = "",
        include_deleted: bool = False,
        limit: int = 50,
    ) -> List[AChatterTask]:
        """列出任务。"""

        return await asyncio.to_thread(
            self._list_tasks_sync,
            target_stream_id,
            creator_platform,
            creator_user_id,
            include_deleted,
            limit,
        )

    async def get_task(self, task_id: str) -> Optional[AChatterTask]:
        """按 ID 读取任务。"""

        return await asyncio.to_thread(self._get_task_sync, task_id)

    async def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        """更新任务状态。"""

        async with self._write_lock:
            return await asyncio.to_thread(self._update_task_status_sync, task_id, status)

    async def list_due_tasks(self, now: datetime) -> List[AChatterTask]:
        """列出到期任务。"""

        return await asyncio.to_thread(self._list_due_tasks_sync, now)

    async def mark_task_run(self, task: AChatterTask, *, next_run_at: Optional[datetime]) -> None:
        """更新任务最近运行时间和下次运行时间。"""

        async with self._write_lock:
            await asyncio.to_thread(self._mark_task_run_sync, task, next_run_at)

    async def record_run(
        self,
        *,
        task_id: str,
        target_stream_id: str,
        status: str,
        used_fallback: bool = False,
        error: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录一次任务运行。"""

        async with self._write_lock:
            return await asyncio.to_thread(
                self._record_run_sync,
                task_id,
                target_stream_id,
                status,
                used_fallback,
                error,
                metadata or {},
            )

    async def get_target_state(self, target_stream_id: str) -> TargetState:
        """读取目标状态。"""

        return await asyncio.to_thread(self._get_target_state_sync, target_stream_id)

    async def update_target_state(self, state: TargetState) -> None:
        """更新目标状态。"""

        async with self._write_lock:
            await asyncio.to_thread(self._update_target_state_sync, state)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_sync(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_confirmations (
                    draft_id TEXT PRIMARY KEY,
                    creator_platform TEXT NOT NULL,
                    creator_user_id TEXT NOT NULL,
                    source_stream_id TEXT NOT NULL,
                    draft_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    task_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    creator_platform TEXT NOT NULL,
                    creator_user_id TEXT NOT NULL,
                    source_stream_id TEXT NOT NULL,
                    target_platform TEXT NOT NULL,
                    target_chat_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_stream_id TEXT NOT NULL,
                    schedule_kind TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    cron_expr TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    timezone TEXT NOT NULL,
                    user_intent TEXT NOT NULL,
                    must_say INTEGER NOT NULL,
                    requires_web INTEGER NOT NULL,
                    web_query TEXT NOT NULL,
                    memory_query TEXT NOT NULL,
                    enabled_sources_json TEXT NOT NULL,
                    style_hint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_run_at TEXT NOT NULL,
                    next_run_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(status, next_run_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_target ON tasks(target_stream_id);

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    target_stream_id TEXT NOT NULL,
                    triggered_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    maisaka_task_id TEXT NOT NULL,
                    used_fallback INTEGER NOT NULL,
                    error TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rbac_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    role TEXT NOT NULL,
                    target TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS target_state (
                    target_stream_id TEXT PRIMARY KEY,
                    last_auto_run_at TEXT NOT NULL,
                    last_schedule_run_at TEXT NOT NULL,
                    last_message_seen_at TEXT NOT NULL,
                    daily_auto_count INTEGER NOT NULL,
                    daily_fallback_count INTEGER NOT NULL,
                    date_key TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )
            connection.commit()

    def _save_pending_sync(self, draft: TaskDraft, max_pending_per_user: int) -> None:
        now = utc_now()
        self._delete_expired_pending_sync(now)
        draft_json = json.dumps(self._draft_to_dict(draft), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO pending_confirmations(
                    draft_id, creator_platform, creator_user_id, source_stream_id,
                    draft_json, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.draft_id,
                    draft.creator_platform,
                    draft.creator_user_id,
                    draft.source_stream_id,
                    draft_json,
                    to_utc_iso(draft.expires_at),
                    to_utc_iso(draft.created_at),
                ),
            )
            rows = connection.execute(
                """
                SELECT draft_id FROM pending_confirmations
                WHERE creator_platform = ? AND creator_user_id = ?
                ORDER BY created_at DESC
                """,
                (draft.creator_platform, draft.creator_user_id),
            ).fetchall()
            overflow_ids = [str(row["draft_id"]) for row in rows[max(1, int(max_pending_per_user)) :]]
            for overflow_id in overflow_ids:
                connection.execute("DELETE FROM pending_confirmations WHERE draft_id = ?", (overflow_id,))
            connection.commit()

    def _get_pending_for_actor_sync(
        self,
        creator_platform: str,
        creator_user_id: str,
        draft_id: str = "",
    ) -> Optional[TaskDraft]:
        drafts = self._list_pending_for_actor_sync(creator_platform, creator_user_id)
        if draft_id:
            for draft in drafts:
                if draft.draft_id == draft_id:
                    return draft
            return None
        if len(drafts) == 1:
            return drafts[0]
        return None

    def _list_pending_for_actor_sync(self, creator_platform: str, creator_user_id: str) -> List[TaskDraft]:
        now = utc_now()
        self._delete_expired_pending_sync(now)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT draft_json FROM pending_confirmations
                WHERE creator_platform = ? AND creator_user_id = ?
                ORDER BY created_at DESC
                """,
                (creator_platform, creator_user_id),
            ).fetchall()
        return [self._draft_from_dict(from_json_dict(str(row["draft_json"]))) for row in rows]

    def _delete_pending_sync(self, draft_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM pending_confirmations WHERE draft_id = ?", (draft_id,))
            connection.commit()
            return cursor.rowcount > 0

    def _create_task_from_draft_sync(self, draft: TaskDraft) -> AChatterTask:
        now = utc_now()
        task = AChatterTask(
            task_id=make_id("task"),
            task_type=draft.task_type,
            title=draft.title,
            status=TaskStatus.ACTIVE,
            creator_platform=draft.creator_platform,
            creator_user_id=draft.creator_user_id,
            source_stream_id=draft.source_stream_id,
            target=draft.target,
            schedule=draft.schedule,
            content=draft.content,
            created_at=now,
            updated_at=now,
            next_run_at=self._initial_next_run_at(draft),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks(
                    task_id, task_type, title, status, creator_platform, creator_user_id, source_stream_id,
                    target_platform, target_chat_type, target_id, target_stream_id,
                    schedule_kind, run_at, cron_expr, interval_seconds, timezone,
                    user_intent, must_say, requires_web, web_query, memory_query, enabled_sources_json, style_hint,
                    created_at, updated_at, last_run_at, next_run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._task_to_row(task),
            )
            connection.execute("DELETE FROM pending_confirmations WHERE draft_id = ?", (draft.draft_id,))
            connection.commit()
        return task

    def _list_tasks_sync(
        self,
        target_stream_id: str,
        creator_platform: str,
        creator_user_id: str,
        include_deleted: bool,
        limit: int,
    ) -> List[AChatterTask]:
        clauses: List[str] = []
        params: List[Any] = []
        if target_stream_id:
            clauses.append("target_stream_id = ?")
            params.append(target_stream_id)
        if creator_platform and creator_user_id:
            clauses.append("creator_platform = ? AND creator_user_id = ?")
            params.extend([creator_platform, creator_user_id])
        if not include_deleted:
            clauses.append("status != ?")
            params.append(TaskStatus.DELETED.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def _get_task_sync(self, task_id: str) -> Optional[AChatterTask]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._task_from_row(row)

    def _update_task_status_sync(self, task_id: str, status: TaskStatus) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status.value, to_utc_iso(utc_now()), task_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def _list_due_tasks_sync(self, now: datetime) -> List[AChatterTask]:
        now_iso = to_utc_iso(now)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tasks
                WHERE status = ? AND next_run_at != '' AND next_run_at <= ?
                ORDER BY next_run_at ASC
                LIMIT 20
                """,
                (TaskStatus.ACTIVE.value, now_iso),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def _mark_task_run_sync(self, task: AChatterTask, next_run_at: Optional[datetime]) -> None:
        status = task.status
        if task.schedule.kind == ScheduleKind.ONCE and next_run_at is None:
            status = TaskStatus.COMPLETED
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, last_run_at = ?, next_run_at = ?
                WHERE task_id = ?
                """,
                (status.value, to_utc_iso(utc_now()), to_utc_iso(utc_now()), to_utc_iso(next_run_at), task.task_id),
            )
            connection.commit()

    def _record_run_sync(
        self,
        task_id: str,
        target_stream_id: str,
        status: str,
        used_fallback: bool,
        error: str,
        metadata: Dict[str, Any],
    ) -> str:
        run_id = make_id("run")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs(
                    run_id, task_id, target_stream_id, triggered_at, status,
                    maisaka_task_id, used_fallback, error, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task_id,
                    target_stream_id,
                    to_utc_iso(utc_now()),
                    status,
                    str(metadata.get("maisaka_task_id") or ""),
                    1 if used_fallback else 0,
                    error,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            connection.commit()
        return run_id

    def _get_target_state_sync(self, target_stream_id: str) -> TargetState:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM target_state WHERE target_stream_id = ?",
                (target_stream_id,),
            ).fetchone()
        if row is None:
            return TargetState(target_stream_id=target_stream_id, date_key=utc_now().strftime("%Y-%m-%d"))
        return TargetState(
            target_stream_id=str(row["target_stream_id"]),
            last_auto_run_at=parse_datetime(row["last_auto_run_at"]),
            last_schedule_run_at=parse_datetime(row["last_schedule_run_at"]),
            last_message_seen_at=parse_datetime(row["last_message_seen_at"]),
            daily_auto_count=int(row["daily_auto_count"]),
            daily_fallback_count=int(row["daily_fallback_count"]),
            date_key=str(row["date_key"]),
        )

    def _update_target_state_sync(self, state: TargetState) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO target_state(
                    target_stream_id, last_auto_run_at, last_schedule_run_at, last_message_seen_at,
                    daily_auto_count, daily_fallback_count, date_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.target_stream_id,
                    to_utc_iso(state.last_auto_run_at),
                    to_utc_iso(state.last_schedule_run_at),
                    to_utc_iso(state.last_message_seen_at),
                    state.daily_auto_count,
                    state.daily_fallback_count,
                    state.date_key,
                ),
            )
            connection.commit()

    def _delete_expired_pending_sync(self, now: datetime) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM pending_confirmations WHERE expires_at <= ?", (to_utc_iso(now),))
            connection.commit()

    @staticmethod
    def _initial_next_run_at(draft: TaskDraft) -> Optional[datetime]:
        if draft.schedule.kind == ScheduleKind.ONCE:
            return draft.schedule.run_at
        if draft.schedule.kind == ScheduleKind.INTERVAL:
            return draft.schedule.run_at or utc_now()
        if draft.schedule.kind == ScheduleKind.CRON:
            return draft.schedule.run_at
        return None

    @staticmethod
    def _draft_to_dict(draft: TaskDraft) -> Dict[str, Any]:
        return {
            "task_type": draft.task_type.value,
            "title": draft.title,
            "target": {
                "platform": draft.target.platform,
                "chat_type": draft.target.chat_type,
                "target_id": draft.target.target_id,
                "stream_id": draft.target.stream_id,
            },
            "schedule": {
                "kind": draft.schedule.kind.value,
                "timezone": draft.schedule.timezone,
                "run_at": to_utc_iso(draft.schedule.run_at),
                "cron": draft.schedule.cron,
                "interval_seconds": draft.schedule.interval_seconds,
            },
            "content": {
                "user_intent": draft.content.user_intent,
                "must_say": draft.content.must_say,
                "requires_web": draft.content.requires_web,
                "web_query": draft.content.web_query,
                "memory_query": draft.content.memory_query,
                "style_hint": draft.content.style_hint,
                "enabled_sources": draft.content.enabled_sources,
            },
            "confidence": draft.confidence,
            "ambiguities": draft.ambiguities,
            "draft_id": draft.draft_id,
            "creator_platform": draft.creator_platform,
            "creator_user_id": draft.creator_user_id,
            "source_stream_id": draft.source_stream_id,
            "created_at": to_utc_iso(draft.created_at),
            "expires_at": to_utc_iso(draft.expires_at),
        }

    @staticmethod
    def _draft_from_dict(data: Dict[str, Any]) -> TaskDraft:
        target_data = data.get("target") if isinstance(data.get("target"), dict) else {}
        schedule_data = data.get("schedule") if isinstance(data.get("schedule"), dict) else {}
        content_data = data.get("content") if isinstance(data.get("content"), dict) else {}
        return TaskDraft(
            task_type=TaskType(str(data.get("task_type") or TaskType.REMINDER.value)),
            title=str(data.get("title") or "未命名任务"),
            target=ChatTarget(
                platform=str(target_data.get("platform") or "qq"),
                chat_type=str(target_data.get("chat_type") or "private"),
                target_id=str(target_data.get("target_id") or ""),
                stream_id=str(target_data.get("stream_id") or ""),
            ),
            schedule=ScheduleSpec(
                kind=ScheduleKind(str(schedule_data.get("kind") or ScheduleKind.ONCE.value)),
                timezone=str(schedule_data.get("timezone") or "Asia/Shanghai"),
                run_at=parse_datetime(schedule_data.get("run_at")),
                cron=str(schedule_data.get("cron") or ""),
                interval_seconds=int(schedule_data.get("interval_seconds") or 0),
            ),
            content=TaskContent(
                user_intent=str(content_data.get("user_intent") or ""),
                must_say=bool(content_data.get("must_say", False)),
                requires_web=bool(content_data.get("requires_web", False)),
                web_query=str(content_data.get("web_query") or ""),
                memory_query=str(content_data.get("memory_query") or ""),
                style_hint=str(content_data.get("style_hint") or ""),
                enabled_sources=list(content_data.get("enabled_sources") or []),
            ),
            confidence=float(data.get("confidence") or 0.0),
            ambiguities=list(data.get("ambiguities") or []),
            draft_id=str(data.get("draft_id") or ""),
            creator_platform=str(data.get("creator_platform") or ""),
            creator_user_id=str(data.get("creator_user_id") or ""),
            source_stream_id=str(data.get("source_stream_id") or ""),
            created_at=parse_datetime(data.get("created_at")) or utc_now(),
            expires_at=parse_datetime(data.get("expires_at")),
        )

    @staticmethod
    def _task_to_row(task: AChatterTask) -> tuple[Any, ...]:
        return (
            task.task_id,
            task.task_type.value,
            task.title,
            task.status.value,
            task.creator_platform,
            task.creator_user_id,
            task.source_stream_id,
            task.target.platform,
            task.target.chat_type,
            task.target.target_id,
            task.target.stream_id,
            task.schedule.kind.value,
            to_utc_iso(task.schedule.run_at),
            task.schedule.cron,
            task.schedule.interval_seconds,
            task.schedule.timezone,
            task.content.user_intent,
            1 if task.content.must_say else 0,
            1 if task.content.requires_web else 0,
            task.content.web_query,
            task.content.memory_query,
            json.dumps(task.content.enabled_sources, ensure_ascii=False),
            task.content.style_hint,
            to_utc_iso(task.created_at),
            to_utc_iso(task.updated_at),
            to_utc_iso(task.last_run_at),
            to_utc_iso(task.next_run_at),
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> AChatterTask:
        return AChatterTask(
            task_id=str(row["task_id"]),
            task_type=TaskType(str(row["task_type"])),
            title=str(row["title"]),
            status=TaskStatus(str(row["status"])),
            creator_platform=str(row["creator_platform"]),
            creator_user_id=str(row["creator_user_id"]),
            source_stream_id=str(row["source_stream_id"]),
            target=ChatTarget(
                platform=str(row["target_platform"]),
                chat_type=str(row["target_chat_type"]),
                target_id=str(row["target_id"]),
                stream_id=str(row["target_stream_id"]),
            ),
            schedule=ScheduleSpec(
                kind=ScheduleKind(str(row["schedule_kind"])),
                timezone=str(row["timezone"] or "Asia/Shanghai"),
                run_at=parse_datetime(row["run_at"]),
                cron=str(row["cron_expr"]),
                interval_seconds=int(row["interval_seconds"]),
            ),
            content=TaskContent(
                user_intent=str(row["user_intent"]),
                must_say=bool(row["must_say"]),
                requires_web=bool(row["requires_web"]),
                web_query=str(row["web_query"]),
                memory_query=str(row["memory_query"]),
                enabled_sources=list(json.loads(row["enabled_sources_json"] or "[]")),
                style_hint=str(row["style_hint"]),
            ),
            created_at=parse_datetime(row["created_at"]) or utc_now(),
            updated_at=parse_datetime(row["updated_at"]) or utc_now(),
            last_run_at=parse_datetime(row["last_run_at"]),
            next_run_at=parse_datetime(row["next_run_at"]),
        )
