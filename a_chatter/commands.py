"""A_chatter 聊天命令处理。"""

from typing import Any, Dict, List

from .models import AChatterTask
from .parser import TaskNeedsClarification, TaskParseError
from .service import AChatterService, format_task_summary


class AChatterCommandService:
    """处理 `/ac`、`/闲谈`、`/进阶闲谈` 命令。"""

    def __init__(self, service: AChatterService) -> None:
        self._service = service

    async def handle(self, command_text: str, stream_id: str, context: Dict[str, Any]) -> tuple[bool, str, bool]:
        """处理命令并发送用户可见响应。"""

        normalized = str(command_text or "").strip()
        try:
            response = await self._dispatch(normalized, context)
            await self._service.ctx.send.text(response, stream_id)
            return True, response, True
        except (PermissionError, TaskNeedsClarification, TaskParseError, ValueError) as exc:
            message = str(exc)
            await self._service.ctx.send.text(message, stream_id)
            return False, message, True

    async def _dispatch(self, command_text: str, context: Dict[str, Any]) -> str:
        if not command_text or command_text in {"帮助", "help", "?"}:
            return self._help_text()

        command, _, rest = command_text.partition(" ")
        command = command.strip()
        rest = rest.strip()

        if command in {"新增", "创建", "add", "create"}:
            if not rest:
                raise ValueError("请提供任务内容，例如 `/ac 新增 明天晚上八点提醒我交报告`")
            _, confirmation_text = await self._service.create_draft(rest, context)
            return confirmation_text

        if command in {"确认", "confirm"}:
            task = await self._service.confirm_draft(context, rest)
            return f"已创建任务：\n{format_task_summary(task)}"

        if command in {"取消", "cancel"}:
            draft_id = await self._service.cancel_draft(context, rest)
            return f"已取消草稿：{draft_id}"

        if command in {"列表", "list"}:
            return self._format_task_list(await self._service.list_tasks_for_context(context, rest))

        if command in {"查看", "view"}:
            if not rest:
                raise ValueError("请提供任务 ID")
            task = await self._service.get_task_for_actor(context, rest)
            return self._format_task_detail(task)

        if command in {"暂停", "恢复", "删除", "立即运行", "pause", "resume", "delete", "run"}:
            if not rest:
                raise ValueError("请提供任务 ID")
            return await self._service.manage_task(context, rest, command)

        if command in {"状态", "权限", "频率", "检索状态", "status", "permissions", "frequency", "tavily"}:
            return self._service.query_status(context, command)

        raise ValueError("未知命令。发送 `/ac 帮助` 查看可用命令")

    @staticmethod
    def _format_task_list(tasks: List[AChatterTask]) -> str:
        if not tasks:
            return "当前没有可见任务。"
        lines = ["A_chatter 任务列表："]
        lines.extend(format_task_summary(task) for task in tasks)
        return "\n".join(lines)

    @staticmethod
    def _format_task_detail(task: AChatterTask) -> str:
        return (
            "任务详情：\n"
            f"ID：{task.task_id}\n"
            f"标题：{task.title}\n"
            f"类型：{task.task_type.value}\n"
            f"状态：{task.status.value}\n"
            f"目标：{task.target.key}\n"
            f"目标 stream_id：{task.target.stream_id}\n"
            f"用户意图：{task.content.user_intent}\n"
            f"下次触发：{task.next_run_at.isoformat() if task.next_run_at else '无'}\n"
            f"创建者：{task.creator_platform}:{task.creator_user_id}"
        )

    @staticmethod
    def _help_text() -> str:
        return (
            "A_chatter 进阶闲谈家命令：\n"
            "/ac 新增 <自然语言任务>\n"
            "/ac 确认 [草稿ID]\n"
            "/ac 取消 [草稿ID]\n"
            "/ac 列表 [当前|platform:group/private:id]\n"
            "/ac 查看 <任务ID>\n"
            "/ac 暂停|恢复|删除|立即运行 <任务ID>\n"
            "/ac 状态|权限|频率|检索状态"
        )

