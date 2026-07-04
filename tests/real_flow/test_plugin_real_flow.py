"""A_chatter 插件生命周期真实流程测试。"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from src.plugin_runtime.host.component_registry import ComponentRegistry
from src.plugin_runtime.host.hook_dispatcher import HookDispatcher
from src.plugin_runtime.protocol.envelope import Envelope, MessageType
from tests.helpers import FakeContext, build_confirmation_response, build_future_parse_response
from tests.runtime_loader import load_plugin_module


plugin_module = load_plugin_module()
AChatterConfig = plugin_module.AChatterConfig
AChatterPlugin = plugin_module.AChatterPlugin


def _inject_plugin_runtime(plugin: AChatterPlugin, context: FakeContext, tmp_path: Path) -> None:
    """注入插件运行时上下文并改写存储路径到临时目录。"""

    del tmp_path

    plugin._set_context(context)
    config = AChatterConfig()
    config.proactive.maisaka_wait_seconds = 0
    plugin.set_plugin_config(config.model_dump(mode="python"))


@pytest.mark.asyncio
async def test_plugin_command_real_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """通过插件命令 handler 走创建、确认、列表的真实调用路径。"""

    plugin = AChatterPlugin()
    context = FakeContext([build_future_parse_response(), build_confirmation_response()])
    _inject_plugin_runtime(plugin, context, tmp_path)

    original_resolve = Path.resolve

    def fake_resolve(path: Path) -> Path:
        resolved = original_resolve(path)
        if resolved.name == "plugin.py" and resolved.parent.name == "A_chatter":
            return tmp_path / "plugin.py"
        return resolved

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    await plugin.on_load()
    try:
        create_result = await plugin.handle_a_chatter_command(
            stream_id="qq-private-10000",
            matched_groups={"ac_command": "新增 明天晚上八点提醒我交报告"},
            platform="qq",
            user_id="10000",
        )
        assert create_result[0] is True
        assert "/ac 确认" in context.send.sent_texts[-1][1]
        assert "/ac 取消" in context.send.sent_texts[-1][1]

        confirm_result = await plugin.handle_a_chatter_command(
            stream_id="qq-private-10000",
            matched_groups={"ac_command": "确认"},
            platform="qq",
            user_id="10000",
        )
        assert confirm_result[0] is True
        assert "已创建任务" in context.send.sent_texts[-1][1]

        list_result = await plugin.handle_a_chatter_command(
            stream_id="qq-private-10000",
            matched_groups={"ac_command": "列表 当前"},
            platform="qq",
            user_id="10000",
        )
        assert list_result[0] is True
        assert "交报告提醒" in context.send.sent_texts[-1][1]
    finally:
        await plugin.on_unload()


@pytest.mark.asyncio
async def test_plugin_tool_real_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """通过插件 Tool handler 走自然语言创建和确认的真实调用路径。"""

    plugin = AChatterPlugin()
    context = FakeContext([build_future_parse_response(), build_confirmation_response()])
    _inject_plugin_runtime(plugin, context, tmp_path)

    original_resolve = Path.resolve

    def fake_resolve(path: Path) -> Path:
        resolved = original_resolve(path)
        if resolved.name == "plugin.py" and resolved.parent.name == "A_chatter":
            return tmp_path / "plugin.py"
        return resolved

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    await plugin.on_load()
    try:
        draft_result = await plugin.handle_create_task_draft(
            user_request="明天晚上八点提醒我交报告",
            stream_id="qq-private-10000",
            platform="qq",
            user_id="10000",
        )
        assert draft_result["success"] is True
        assert draft_result["requires_user_confirmation"] is True

        confirm_result = await plugin.handle_confirm_task(
            stream_id="qq-private-10000",
            platform="qq",
            user_id="10000",
        )
        assert confirm_result["success"] is True
        assert "交报告提醒" in confirm_result["task_summary"]
    finally:
        await plugin.on_unload()


@pytest.mark.asyncio
async def test_plugin_hook_natural_confirmation_real_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """通过插件 Hook handler 模拟父项目消息链自然语言确认。"""

    plugin = AChatterPlugin()
    context = FakeContext([build_future_parse_response(), build_confirmation_response()])
    _inject_plugin_runtime(plugin, context, tmp_path)

    original_resolve = Path.resolve

    def fake_resolve(path: Path) -> Path:
        resolved = original_resolve(path)
        if resolved.name == "plugin.py" and resolved.parent.name == "A_chatter":
            return tmp_path / "plugin.py"
        return resolved

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    await plugin.on_load()
    try:
        draft_result = await plugin.handle_create_task_draft(
            user_request="明天晚上八点提醒我交报告",
            stream_id="qq-private-10000",
            platform="qq",
            user_id="10000",
        )
        assert draft_result["success"] is True

        hook_result = await plugin.handle_natural_confirmation_reply(
            message={
                "platform": "qq",
                "session_id": "qq-private-10000",
                "processed_plain_text": "就这样，帮我设上",
                "message_info": {
                    "user_info": {"user_id": "10000", "user_nickname": "测试用户"},
                    "group_info": None,
                },
                "raw_message": [{"type": "text", "data": "就这样，帮我设上"}],
            }
        )

        assert hook_result["action"] == "abort"
        assert context.send.sent_texts[-1][0] == "qq-private-10000"
        assert "已创建任务" in context.send.sent_texts[-1][1]
    finally:
        await plugin.on_unload()


@pytest.mark.asyncio
async def test_host_hook_dispatcher_aborts_after_natural_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """通过父项目 HookDispatcher 分发自然确认 Hook。"""

    plugin = AChatterPlugin()
    context = FakeContext([build_future_parse_response(), build_confirmation_response()])
    _inject_plugin_runtime(plugin, context, tmp_path)

    original_resolve = Path.resolve

    def fake_resolve(path: Path) -> Path:
        resolved = original_resolve(path)
        if resolved.name == "plugin.py" and resolved.parent.name == "A_chatter":
            return tmp_path / "plugin.py"
        return resolved

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    await plugin.on_load()
    try:
        draft_result = await plugin.handle_create_task_draft(
            user_request="明天晚上八点提醒我交报告",
            stream_id="qq-private-10000",
            platform="qq",
            user_id="10000",
        )
        assert draft_result["success"] is True

        registry = ComponentRegistry()
        component = next(item for item in plugin.get_components() if item["name"] == "natural_confirmation_reply")
        registry.register_component(
            name=component["name"],
            component_type=component["type"],
            plugin_id="github.A-Dawn.a-chatter",
            metadata=component["metadata"],
        )

        async def invoke_plugin(method: str, plugin_id: str, component_name: str, args: Dict[str, Any], timeout_ms: int = 0) -> Envelope:
            del timeout_ms
            assert method == "plugin.invoke_hook"
            assert plugin_id == "github.A-Dawn.a-chatter"
            assert component_name == "natural_confirmation_reply"
            payload = await plugin.handle_natural_confirmation_reply(**args)
            return Envelope(
                request_id=1,
                message_type=MessageType.RESPONSE,
                method=method,
                plugin_id=plugin_id,
                payload=payload,
            )

        supervisor = SimpleNamespace(
            group_name="third_party",
            component_registry=registry,
            invoke_plugin=invoke_plugin,
        )
        dispatcher = HookDispatcher()
        result = await dispatcher.invoke_hook(
            "chat.receive.after_process",
            supervisors=[supervisor],
            message={
                "platform": "qq",
                "session_id": "qq-private-10000",
                "processed_plain_text": "确认，就这样",
                "message_info": {
                    "user_info": {"user_id": "10000", "user_nickname": "测试用户"},
                    "group_info": None,
                },
                "raw_message": [{"type": "text", "data": "确认，就这样"}],
            },
        )

        assert result.aborted is True
        assert result.stopped_by == "github.A-Dawn.a-chatter.natural_confirmation_reply"
        assert context.send.sent_texts[-1][0] == "qq-private-10000"
        assert "已创建任务" in context.send.sent_texts[-1][1]
    finally:
        await plugin.on_unload()
