"""A_chatter 通用工具函数。"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import json
import re
import uuid

from .models import Actor, ChatTarget


TARGET_PATTERN = re.compile(r"^(?P<platform>[^:\s]+):(?P<chat_type>group|private):(?P<target_id>[^:\s]+)$")


def utc_now() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def ensure_aware_datetime(value: datetime) -> datetime:
    """确保 datetime 带时区。"""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def parse_datetime(value: Any) -> Optional[datetime]:
    """解析 ISO datetime。"""

    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_aware_datetime(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return ensure_aware_datetime(datetime.fromisoformat(text))
    except ValueError:
        return None


def to_utc_iso(value: Optional[datetime]) -> str:
    """将时间转为 UTC ISO 字符串。"""

    if value is None:
        return ""
    return ensure_aware_datetime(value).astimezone(timezone.utc).isoformat()


def from_json_dict(value: str) -> Dict[str, Any]:
    """解析 JSON 字典。"""

    if not value:
        return {}
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("JSON 内容必须是对象")
    return loaded


def make_id(prefix: str) -> str:
    """生成稳定业务 ID。"""

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def normalize_platform(value: Any) -> str:
    """规范化平台名。"""

    return str(value or "qq").strip().lower() or "qq"


def normalize_id(value: Any) -> str:
    """规范化平台 ID。"""

    return str(value or "").strip()


def parse_target(value: str) -> Optional[ChatTarget]:
    """解析 platform:group/private:id 目标。"""

    match = TARGET_PATTERN.match(str(value or "").strip())
    if match is None:
        return None
    return ChatTarget(
        platform=normalize_platform(match.group("platform")),
        chat_type=match.group("chat_type"),
        target_id=normalize_id(match.group("target_id")),
    )


def build_actor(context: Dict[str, Any]) -> Actor:
    """从 SDK 上下文字段构造 Actor。"""

    stream_id = normalize_id(context.get("stream_id") or context.get("chat_id"))
    platform = normalize_platform(context.get("platform"))
    user_id = normalize_id(context.get("user_id"))
    group_id = normalize_id(context.get("group_id"))
    return Actor(platform=platform, user_id=user_id, stream_id=stream_id, group_id=group_id)


def default_target_from_context(context: Dict[str, Any]) -> ChatTarget:
    """根据当前聊天上下文构造默认目标。"""

    actor = build_actor(context)
    if actor.group_id:
        return ChatTarget(platform=actor.platform, chat_type="group", target_id=actor.group_id, stream_id=actor.stream_id)
    return ChatTarget(platform=actor.platform, chat_type="private", target_id=actor.user_id, stream_id=actor.stream_id)


def extract_stream_id(stream: Any) -> str:
    """从 SDK 聊天流响应中提取真实 stream_id。"""

    if not isinstance(stream, dict):
        return ""
    stream_id = normalize_id(stream.get("stream_id") or stream.get("session_id"))
    if stream_id:
        return stream_id
    nested_stream = stream.get("stream")
    if isinstance(nested_stream, dict):
        return normalize_id(nested_stream.get("stream_id") or nested_stream.get("session_id"))
    return ""


def extract_messages(payload: Any) -> Any:
    """从 message.get_recent 响应中提取消息列表。"""

    if isinstance(payload, dict) and "messages" in payload:
        return payload["messages"]
    return payload


def extract_readable_text(payload: Any) -> str:
    """从 message.build_readable 响应中提取文本。"""

    if isinstance(payload, dict):
        return str(payload.get("text") or payload.get("content") or "")
    return str(payload or "")


def extract_llm_response(payload: Any) -> str:
    """从 LLM 响应中提取文本。"""

    if isinstance(payload, dict):
        return str(payload.get("response") or payload.get("content") or "")
    return str(payload or "")

