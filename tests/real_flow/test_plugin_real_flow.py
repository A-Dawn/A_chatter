"""A_chatter 插件生命周期真实流程测试。"""

from pathlib import Path

import pytest

from a_chatter.config import AChatterConfig
from plugin import AChatterPlugin
from tests.helpers import FakeContext, build_future_parse_response


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
    context = FakeContext([build_future_parse_response()])
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
        assert "请确认是否创建" in context.send.sent_texts[-1][1]

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
    context = FakeContext([build_future_parse_response()])
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
