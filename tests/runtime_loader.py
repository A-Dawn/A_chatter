"""按 MaiBot 运行时方式加载 A_chatter 插件入口。"""

from pathlib import Path

import contextlib
import importlib.util
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_MODULE_NAME = "_a_chatter_plugin_runtime_test"


def load_plugin_module():
    """使用 package-style spec 加载 plugin.py，覆盖相对导入路径。"""

    module = sys.modules.get(PLUGIN_MODULE_NAME)
    if module is not None:
        return module

    spec = importlib.util.spec_from_file_location(
        PLUGIN_MODULE_NAME,
        PLUGIN_ROOT / "plugin.py",
        submodule_search_locations=[str(PLUGIN_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法创建 A_chatter 插件测试模块 spec")

    module = importlib.util.module_from_spec(spec)
    sys.modules[PLUGIN_MODULE_NAME] = module
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        spec.loader.exec_module(module)
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(PROJECT_ROOT))
    return module
