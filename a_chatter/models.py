"""A_chatter 业务模型。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskType(str, Enum):
    """任务类型。"""

    REMINDER = "reminder"
    SCHEDULE_PROACTIVE = "schedule_proactive"
    AUTO_PROACTIVE = "auto_proactive"
    RESEARCH_DIGEST = "research_digest"


class TaskStatus(str, Enum):
    """任务状态。"""

    ACTIVE = "active"
    PAUSED = "paused"
    DELETED = "deleted"
    COMPLETED = "completed"


class ScheduleKind(str, Enum):
    """日程类型。"""

    ONCE = "once"
    CRON = "cron"
    INTERVAL = "interval"


class RunStatus(str, Enum):
    """运行记录状态。"""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Actor:
    """发起操作的用户。"""

    platform: str
    user_id: str
    stream_id: str = ""
    group_id: str = ""

    @property
    def subject(self) -> str:
        """返回 RBAC 主体字符串。"""

        if not self.platform or not self.user_id:
            return ""
        return f"{self.platform}:{self.user_id}"


@dataclass(frozen=True)
class ChatTarget:
    """聊天目标。"""

    platform: str
    chat_type: str
    target_id: str
    stream_id: str = ""

    @property
    def key(self) -> str:
        """返回平台目标字符串。"""

        return f"{self.platform}:{self.chat_type}:{self.target_id}"


@dataclass
class ScheduleSpec:
    """任务日程描述。"""

    kind: ScheduleKind
    timezone: str = "Asia/Shanghai"
    run_at: Optional[datetime] = None
    cron: str = ""
    interval_seconds: int = 0


@dataclass
class TaskContent:
    """任务内容。"""

    user_intent: str
    must_say: bool = False
    requires_web: bool = False
    web_query: str = ""
    memory_query: str = ""
    style_hint: str = ""
    enabled_sources: List[str] = field(default_factory=list)


@dataclass
class TaskDraft:
    """待确认任务草稿。"""

    task_type: TaskType
    title: str
    target: ChatTarget
    schedule: ScheduleSpec
    content: TaskContent
    confidence: float
    ambiguities: List[str] = field(default_factory=list)
    draft_id: str = ""
    creator_platform: str = ""
    creator_user_id: str = ""
    source_stream_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None


@dataclass
class AChatterTask:
    """正式任务。"""

    task_id: str
    task_type: TaskType
    title: str
    status: TaskStatus
    creator_platform: str
    creator_user_id: str
    source_stream_id: str
    target: ChatTarget
    schedule: ScheduleSpec
    content: TaskContent
    created_at: datetime
    updated_at: datetime
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None


@dataclass
class PermissionResult:
    """权限判断结果。"""

    allowed: bool
    reason: str = ""


@dataclass
class ContextBundle:
    """主动发言上下文包。"""

    visible_text: str
    intent: str
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TavilyResult:
    """Tavily 检索结果。"""

    title: str
    url: str
    snippet: str = ""
    content: str = ""
    published_at: str = ""
    source: str = "tavily"


@dataclass
class TaskRunResult:
    """任务执行结果。"""

    success: bool
    status: RunStatus
    used_fallback: bool = False
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetState:
    """目标聊天流状态。"""

    target_stream_id: str
    last_auto_run_at: Optional[datetime] = None
    last_schedule_run_at: Optional[datetime] = None
    last_message_seen_at: Optional[datetime] = None
    daily_auto_count: int = 0
    daily_fallback_count: int = 0
    date_key: str = ""

