"""真实 LLM 完整循环测试。

默认跳过。该套件真实调用父项目 LLM capability，但发送、消息、知识和 Maisaka
能力由测试 Host 记录，避免向外部聊天平台发送消息。
"""

from pathlib import Path
from typing import Any, Dict

import os
import pytest

from maibot_sdk.context import PluginContext

from src.plugin_runtime.integration import PluginRuntimeManager

from a_chatter.commands import AChatterCommandService
from a_chatter.config import AChatterConfig
from a_chatter.models import TaskStatus, TaskType
from a_chatter.service import AChatterService


pytestmark = [pytest.mark.live_llm, pytest.mark.live_full_loop]


class LiveLoopHost:
    """测试 Host：LLM 走父项目，其它能力只记录结果。"""

    def __init__(self) -> None:
        self.sent_texts: list[Dict[str, Any]] = []
        self.capability_calls: list[str] = []
        self.maisaka_trigger_should_fail = False

    async def rpc_call(
        self,
        method: str,
        plugin_id: str,
        payload: Dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> Any:
        del timeout_ms
        if method != "cap.call":
            raise AssertionError(f"live_full_loop 测试只允许 cap.call，收到：{method}")
        if not isinstance(payload, dict):
            raise AssertionError("cap.call payload 必须是字典")
        capability = str(payload.get("capability") or "")
        args = payload.get("args")
        if not isinstance(args, dict):
            raise AssertionError("cap.call args 必须是字典")
        self.capability_calls.append(capability)

        if capability == "llm.generate":
            manager = PluginRuntimeManager()
            result = await manager._cap_llm_generate(plugin_id, capability, args)
            if isinstance(result, dict) and result.get("success") is False:
                raise AssertionError(f"父项目 LLM capability 调用失败：{result.get('error') or '未知错误'}")
            return result
        if capability == "send.text":
            self.sent_texts.append(
                {
                    "stream_id": str(args.get("stream_id") or ""),
                    "text": str(args.get("text") or ""),
                    "kwargs": dict(args),
                }
            )
            return {"success": True}
        if capability == "chat.get_stream_by_user_id":
            user_id = str(args.get("user_id") or "")
            platform = str(args.get("platform") or "qq")
            return {"success": True, "stream": {"stream_id": f"{platform}-private-{user_id}"}}
        if capability == "message.get_recent":
            return {"success": True, "messages": []}
        if capability == "message.build_readable":
            return {"success": True, "text": "用户：最近提醒过报告截止时间"}
        if capability == "knowledge.search":
            return {"success": True, "content": "与交报告相关的记忆：今晚截止。"}
        if capability == "maisaka.context.append":
            return {"success": True}
        if capability == "maisaka.proactive.trigger":
            if self.maisaka_trigger_should_fail:
                return {"success": False, "error": "测试环境模拟 Maisaka 未触发"}
            return {"success": True, "task_id": "live_full_loop_proactive"}
        raise AssertionError(f"live_full_loop 测试未开放 capability：{capability}")


def _require_live_llm() -> None:
    if os.environ.get("A_CHATTER_LIVE_LLM") != "1":
        pytest.skip("设置 A_CHATTER_LIVE_LLM=1 后才运行父项目真实 LLM 完整循环测试")


async def _build_service(tmp_path: Path, host: LiveLoopHost) -> AChatterService:
    config = AChatterConfig()
    config.permissions.default_allow_group_schedule = True
    config.proactive.maisaka_wait_seconds = 0
    context = PluginContext("github.A-Dawn.a-chatter", rpc_call=host.rpc_call)
    service = AChatterService(context, config, tmp_path)
    await service.start()
    return service


@pytest.mark.asyncio
async def test_live_llm_command_confirm_and_run_reminder_full_loop(tmp_path: Path) -> None:
    """真实 LLM 解析后，经确认和立即运行，最终生成一条硬提醒发送请求。"""

    _require_live_llm()
    host = LiveLoopHost()
    service = await _build_service(tmp_path, host)
    commands = AChatterCommandService(service)
    sdk_context = {"platform": "qq", "user_id": "10000", "stream_id": "qq-private-10000"}

    success, confirmation_text, _ = await commands.handle("新增 明天晚上八点提醒我交报告", "qq-private-10000", sdk_context)
    assert success is True
    assert "/ac 确认" in confirmation_text
    assert "/ac 取消" in confirmation_text
    assert "llm.generate" in host.capability_calls

    handled, created_text, intent = await service.handle_natural_confirmation_reply(
        "这版可以，就按这个安排吧",
        sdk_context,
    )
    assert handled is True
    assert intent.decision.value == "confirm"
    assert "已创建任务" in created_text

    tasks = await service.storage.list_tasks(target_stream_id="qq-private-10000")
    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_type == TaskType.REMINDER
    assert task.target.stream_id == "qq-private-10000"

    success, run_text, _ = await commands.handle(f"立即运行 {task.task_id}", "qq-private-10000", sdk_context)
    assert success is True
    assert "已触发任务执行" in run_text

    reminder_sends = [
        item
        for item in host.sent_texts
        if item["kwargs"].get("maisaka_source_kind") == "plugin:a-chatter:reminder"
    ]
    assert len(reminder_sends) == 1
    print(f"[A_chatter live_full_loop] reminder_final_message={reminder_sends[0]['text']}")
    assert reminder_sends[0]["stream_id"] == "qq-private-10000"
    assert "交报告" in reminder_sends[0]["text"]
    assert "明天晚上八点" not in reminder_sends[0]["text"]

    updated_task = await service.storage.get_task(task.task_id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_live_llm_schedule_proactive_fallback_generates_final_message(tmp_path: Path) -> None:
    """真实 LLM 解析日程主动任务后，兜底链路应生成最终聊天文本。"""

    _require_live_llm()
    host = LiveLoopHost()
    host.maisaka_trigger_should_fail = True
    service = await _build_service(tmp_path, host)
    commands = AChatterCommandService(service)
    sdk_context = {
        "platform": "qq",
        "user_id": "10000",
        "group_id": "123456",
        "stream_id": "qq-group-123456",
    }

    success, confirmation_text, _ = await commands.handle(
        "新增 明天上午九点问问大家今天项目进度怎么样",
        "qq-group-123456",
        sdk_context,
    )
    assert success is True
    assert "日程主动发言" in confirmation_text
    assert "/ac 确认" in confirmation_text

    success, created_text, _ = await commands.handle("确认", "qq-group-123456", sdk_context)
    assert success is True
    assert "已创建任务" in created_text

    tasks = await service.storage.list_tasks(target_stream_id="qq-group-123456")
    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_type == TaskType.SCHEDULE_PROACTIVE
    assert task.target.stream_id == "qq-group-123456"

    success, run_text, _ = await commands.handle(f"立即运行 {task.task_id}", "qq-group-123456", sdk_context)
    assert success is True
    assert "已触发任务执行" in run_text

    fallback_sends = [
        item
        for item in host.sent_texts
        if item["kwargs"].get("maisaka_source_kind") == "plugin:a-chatter:fallback"
    ]
    assert len(fallback_sends) == 1
    final_message = fallback_sends[0]["text"]
    print(f"[A_chatter live_full_loop] fallback_final_message={final_message}")
    assert fallback_sends[0]["stream_id"] == "qq-group-123456"
    assert "项目" in final_message or "进度" in final_message
    assert "插件" not in final_message
    assert "调度器" not in final_message
    assert "兜底" not in final_message
