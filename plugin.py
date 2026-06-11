"""A_chatter 进阶闲谈家插件入口。"""

from pathlib import Path
from typing import Any, Dict

from maibot_sdk import Command, MaiBotPlugin, Tool

from a_chatter.commands import AChatterCommandService
from a_chatter.config import AChatterConfig
from a_chatter.scheduler import AChatterScheduler
from a_chatter.service import AChatterService
from a_chatter.tools import AChatterToolService


class AChatterPlugin(MaiBotPlugin):
    """进阶闲谈家插件。"""

    config_model = AChatterConfig

    def __init__(self) -> None:
        super().__init__()
        self._service: AChatterService | None = None
        self._commands: AChatterCommandService | None = None
        self._tools: AChatterToolService | None = None
        self._scheduler: AChatterScheduler | None = None

    async def on_load(self) -> None:
        """加载插件并启动后台调度器。"""

        plugin_root = Path(__file__).resolve().parent
        self._service = AChatterService(self.ctx, self.config, plugin_root)
        await self._service.start()
        self._commands = AChatterCommandService(self._service)
        self._tools = AChatterToolService(self._service)
        self._scheduler = AChatterScheduler(self._service)
        await self._scheduler.start()
        self._get_logger().info("A_chatter 进阶闲谈家已加载")

    async def on_unload(self) -> None:
        """停止后台调度器。"""

        if self._scheduler is not None:
            await self._scheduler.stop()
        self._scheduler = None
        self._tools = None
        self._commands = None
        self._service = None
        self._get_logger().info("A_chatter 进阶闲谈家已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, object], version: str) -> None:
        """处理配置热更新。"""

        del scope
        del config_data
        del version
        if self._service is not None:
            self._service.update_config(self.config)
        self._get_logger().info("A_chatter 配置已更新")

    @Command(
        "a_chatter",
        description="A_chatter 进阶闲谈家任务管理命令",
        pattern=r"^(?:/ac|/闲谈|/进阶闲谈)(?:\s+(?P<ac_command>.*))?$",
    )
    async def handle_a_chatter_command(self, stream_id: str = "", **kwargs: Any):
        """处理聊天命令。"""

        commands = self._require_commands()
        matched_groups = kwargs.get("matched_groups")
        command_text = ""
        if isinstance(matched_groups, dict):
            command_text = str(matched_groups.get("ac_command") or "").strip()
        if not command_text:
            raw_text = str(kwargs.get("text") or kwargs.get("raw_message") or "").strip()
            for prefix in ("/进阶闲谈", "/闲谈", "/ac"):
                if raw_text.startswith(prefix):
                    command_text = raw_text[len(prefix) :].strip()
                    break
        context = self._build_context(stream_id=stream_id, kwargs=kwargs)
        return await commands.handle(command_text, stream_id, context)

    @Tool(
        "a_chatter_create_task_draft",
        description="根据用户自然语言创建 A_chatter 待确认任务草稿，不直接创建正式任务。",
        parameters={
            "type": "object",
            "properties": {
                "user_request": {"type": "string", "description": "用户原始自然语言需求"},
            },
            "required": ["user_request"],
        },
        visibility="visible",
    )
    async def handle_create_task_draft(self, user_request: str = "", stream_id: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Tool：创建待确认任务草稿。"""

        return await self._require_tools().create_task_draft(
            user_request=user_request,
            context=self._build_context(stream_id=stream_id, kwargs=kwargs),
        )

    @Tool(
        "a_chatter_confirm_task",
        description="确认 A_chatter 最近或指定待确认任务草稿。",
        parameters={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "可选草稿 ID；为空时确认当前用户唯一待确认草稿"},
            },
        },
        visibility="visible",
    )
    async def handle_confirm_task(self, draft_id: str = "", stream_id: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Tool：确认任务。"""

        return await self._require_tools().confirm_task(
            draft_id=draft_id,
            context=self._build_context(stream_id=stream_id, kwargs=kwargs),
        )

    @Tool(
        "a_chatter_cancel_draft",
        description="取消 A_chatter 最近或指定待确认任务草稿。",
        parameters={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "可选草稿 ID"},
            },
        },
    )
    async def handle_cancel_draft(self, draft_id: str = "", stream_id: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Tool：取消草稿。"""

        return await self._require_tools().cancel_draft(
            draft_id=draft_id,
            context=self._build_context(stream_id=stream_id, kwargs=kwargs),
        )

    @Tool(
        "a_chatter_list_tasks",
        description="查询 A_chatter 当前聊天流或指定目标的任务。",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "可选目标，格式 platform:group/private:id"},
            },
        },
    )
    async def handle_list_tasks(self, target: str = "", stream_id: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Tool：查询任务。"""

        return await self._require_tools().list_tasks(
            target=target,
            context=self._build_context(stream_id=stream_id, kwargs=kwargs),
        )

    @Tool(
        "a_chatter_manage_task",
        description="管理 A_chatter 任务：暂停、恢复、删除或立即运行。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 ID"},
                "action": {"type": "string", "description": "pause/resume/delete/run 或中文动作"},
            },
            "required": ["task_id", "action"],
        },
    )
    async def handle_manage_task(
        self,
        task_id: str = "",
        action: str = "",
        stream_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Tool：管理任务。"""

        return await self._require_tools().manage_task(
            task_id=task_id,
            action=action,
            context=self._build_context(stream_id=stream_id, kwargs=kwargs),
        )

    @Tool(
        "a_chatter_query_status",
        description="查询 A_chatter 状态、权限、频率或 Tavily 检索状态。",
        parameters={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "status/permissions/frequency/tavily，也可使用中文 状态/权限/频率/检索状态",
                },
            },
        },
    )
    async def handle_query_status(self, scope: str = "status", stream_id: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Tool：查询状态。"""

        return await self._require_tools().query_status(
            scope=scope,
            context=self._build_context(stream_id=stream_id, kwargs=kwargs),
        )

    def _require_commands(self) -> AChatterCommandService:
        if self._commands is None:
            raise RuntimeError("A_chatter 命令服务尚未初始化")
        return self._commands

    def _require_tools(self) -> AChatterToolService:
        if self._tools is None:
            raise RuntimeError("A_chatter 工具服务尚未初始化")
        return self._tools

    @staticmethod
    def _build_context(stream_id: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        context = dict(kwargs)
        if stream_id:
            context["stream_id"] = stream_id
            context.setdefault("chat_id", stream_id)
        return context


def create_plugin() -> AChatterPlugin:
    """创建插件实例。"""

    return AChatterPlugin()

