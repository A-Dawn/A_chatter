"""A_chatter 插件组件注册测试。"""

from plugin import create_plugin


def test_plugin_registers_command_and_visible_tools() -> None:
    plugin = create_plugin()
    components = plugin.get_components()
    names = {component["name"]: component for component in components}

    assert "a_chatter" in names
    assert names["a_chatter"]["type"] == "COMMAND"
    assert names["a_chatter_create_task_draft"]["metadata"]["metadata"]["visibility"] == "visible"
    assert names["a_chatter_confirm_task"]["metadata"]["metadata"]["visibility"] == "visible"
    assert names["natural_confirmation_reply"]["type"] == "HOOK_HANDLER"
    assert names["natural_confirmation_reply"]["metadata"]["hook"] == "chat.receive.after_process"
    assert "user_reply" in names["a_chatter_confirm_task"]["metadata"]["parameters_raw"]["properties"]

