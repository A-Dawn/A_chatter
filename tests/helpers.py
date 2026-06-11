"""A_chatter 测试辅助对象。"""

from datetime import timedelta
from typing import Any, Dict, List

import json

from a_chatter.utils import utc_now


class FakeLogger:
    """测试日志器。"""

    def __init__(self) -> None:
        self.infos: List[str] = []
        self.exceptions: List[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)

    def exception(self, message: str) -> None:
        self.exceptions.append(message)


class FakeLLM:
    """按顺序返回预设 LLM 响应。"""

    def __init__(self, responses: List[str]) -> None:
        self.responses = responses
        self.prompts: List[str] = []

    async def generate(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        self.prompts.append(prompt)
        response = self.responses.pop(0) if self.responses else ""
        return {"success": True, "response": response, "model": kwargs.get("model", "")}


class FakeSend:
    """记录发送文本。"""

    def __init__(self) -> None:
        self.sent_texts: List[tuple[str, str]] = []

    async def text(self, text: str, stream_id: str, **kwargs: Any) -> Dict[str, Any]:
        del kwargs
        self.sent_texts.append((stream_id, text))
        return {"success": True}


class FakeChat:
    """提供聊天流解析。"""

    async def get_stream_by_group_id(self, group_id: str, platform: str = "qq") -> Dict[str, Any]:
        return {"success": True, "stream": {"stream_id": f"{platform}-group-{group_id}"}}

    async def get_stream_by_user_id(self, user_id: str, platform: str = "qq") -> Dict[str, Any]:
        return {"success": True, "stream": {"stream_id": f"{platform}-private-{user_id}"}}


class FakeMessage:
    """提供最近消息和可读文本。"""

    async def get_recent(self, chat_id: str, limit: int = 10) -> Dict[str, Any]:
        del limit
        return {"success": True, "messages": [{"timestamp": utc_now().timestamp(), "text": f"{chat_id} 最近消息"}]}

    async def build_readable(self, messages: Any, **kwargs: Any) -> Dict[str, Any]:
        del messages
        del kwargs
        return {"success": True, "text": "用户：最近在聊项目进度"}


class FakeKnowledge:
    """提供记忆检索。"""

    async def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        del limit
        return {"success": True, "content": f"与 {query} 相关的记忆"}


class FakeMaisaka:
    """记录 Maisaka 上下文注入和主动触发。"""

    def __init__(self) -> None:
        self.appended: List[Dict[str, Any]] = []
        self.triggered: List[Dict[str, Any]] = []

    async def append_context(self, stream_id: str, segments: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        self.appended.append({"stream_id": stream_id, "segments": segments, "kwargs": kwargs})
        return {"success": True}

    async def trigger_proactive(self, stream_id: str, intent: str, **kwargs: Any) -> Dict[str, Any]:
        self.triggered.append({"stream_id": stream_id, "intent": intent, "kwargs": kwargs})
        return {"success": True, "task_id": "proactive_test"}


class FakeContext:
    """组合 fake SDK context。"""

    def __init__(self, llm_responses: List[str]) -> None:
        self.logger = FakeLogger()
        self.llm = FakeLLM(llm_responses)
        self.send = FakeSend()
        self.chat = FakeChat()
        self.message = FakeMessage()
        self.knowledge = FakeKnowledge()
        self.maisaka = FakeMaisaka()


def build_parse_response(run_at: str, task_type: str = "reminder") -> str:
    """构造任务解析 LLM 响应。"""

    return json.dumps(
        {
            "task_type": task_type,
            "title": "交报告提醒",
            "target": {"scope": "current", "platform": "qq", "chat_type": "private", "target_id": "10000"},
            "schedule": {
                "kind": "once",
                "timezone": "Asia/Shanghai",
                "run_at": run_at,
                "cron": "",
                "interval_seconds": 0,
            },
            "content": {
                "user_intent": "提醒我交报告",
                "must_say": task_type != "auto_proactive",
                "requires_web": False,
                "web_query": "",
                "memory_query": "",
                "style_hint": "",
                "enabled_sources": [],
            },
            "safety": {"needs_cross_stream_permission": False, "confidence": 0.92, "ambiguities": []},
        },
        ensure_ascii=False,
    )


def build_future_parse_response(task_type: str = "reminder") -> str:
    """构造一小时后的任务解析响应。"""

    return build_parse_response((utc_now() + timedelta(hours=1)).isoformat(), task_type=task_type)


def default_sdk_context() -> Dict[str, str]:
    """返回默认 SDK 上下文。"""

    return {"platform": "qq", "user_id": "10000", "stream_id": "qq-private-10000"}
