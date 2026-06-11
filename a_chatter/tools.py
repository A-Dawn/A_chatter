"""A_chatter Maisaka Tool 服务。"""

from typing import Any, Dict

from .parser import TaskNeedsClarification, TaskParseError
from .service import AChatterService, format_task_summary


class AChatterToolService:
    """承接 Maisaka Tool 调用并返回结构化结果。"""

    def __init__(self, service: AChatterService) -> None:
        self._service = service

    async def create_task_draft(self, user_request: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """从自然语言创建待确认任务草稿。"""

        try:
            draft, confirmation_text = await self._service.create_draft(user_request, context)
            return {
                "success": True,
                "content": "已创建待确认草稿，请用户确认。",
                "draft_id": draft.draft_id,
                "requires_user_confirmation": True,
                "confirmation_expires_in_seconds": self._service.config.confirmation.pending_ttl_seconds,
                "confirmation_text": confirmation_text,
                "task_preview": {
                    "task_type": draft.task_type.value,
                    "title": draft.title,
                    "target": draft.target.key,
                    "run_at": draft.schedule.run_at.isoformat() if draft.schedule.run_at else "",
                    "schedule_kind": draft.schedule.kind.value,
                },
            }
        except TaskNeedsClarification as exc:
            return {"success": False, "content": str(exc), "needs_clarification": True, "ambiguities": exc.ambiguities}
        except (PermissionError, TaskParseError, ValueError) as exc:
            return {"success": False, "content": str(exc)}

    async def confirm_task(self, draft_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """确认待确认草稿。"""

        try:
            task = await self._service.confirm_draft(context, draft_id)
            return {
                "success": True,
                "content": "任务已创建。",
                "task_id": task.task_id,
                "task_summary": format_task_summary(task),
            }
        except (PermissionError, ValueError) as exc:
            return {"success": False, "content": str(exc)}

    async def cancel_draft(self, draft_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """取消待确认草稿。"""

        try:
            canceled_id = await self._service.cancel_draft(context, draft_id)
            return {"success": True, "content": f"已取消草稿：{canceled_id}", "draft_id": canceled_id}
        except ValueError as exc:
            return {"success": False, "content": str(exc)}

    async def list_tasks(self, target: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """查询任务列表。"""

        try:
            tasks = await self._service.list_tasks_for_context(context, target)
            return {
                "success": True,
                "content": "\n".join(format_task_summary(task) for task in tasks) or "没有可见任务。",
                "tasks": [format_task_summary(task) for task in tasks],
            }
        except (PermissionError, ValueError) as exc:
            return {"success": False, "content": str(exc)}

    async def manage_task(self, task_id: str, action: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """管理任务。"""

        try:
            result = await self._service.manage_task(context, task_id, action)
            return {"success": True, "content": result, "task_id": task_id, "action": action}
        except (PermissionError, ValueError) as exc:
            return {"success": False, "content": str(exc)}

    async def query_status(self, scope: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """查询插件状态。"""

        return {"success": True, "content": self._service.query_status(context, scope)}

