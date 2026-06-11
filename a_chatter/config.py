"""A_chatter 插件配置模型。"""

from typing import List

from maibot_sdk import Field, PluginConfigBase


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "messages-square"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用进阶闲谈家")
    config_version: str = Field(default="0.1.0", description="配置版本")


class PermissionConfig(PluginConfigBase):
    """权限配置。"""

    __ui_label__ = "权限"
    __ui_icon__ = "shield-check"
    __ui_order__ = 1

    super_admins: List[str] = Field(default_factory=list, description="超级管理员，格式 platform:user_id")
    default_allow_private_schedule: bool = Field(default=True, description="是否允许普通用户在私聊创建个人任务")
    default_allow_group_schedule: bool = Field(default=False, description="是否默认允许普通用户在群聊创建群任务")
    allow_cross_stream_by_default: bool = Field(default=False, description="是否默认允许跨聊天流创建任务")


class WhitelistConfig(PluginConfigBase):
    """白名单配置。"""

    __ui_label__ = "白名单"
    __ui_icon__ = "list-checks"
    __ui_order__ = 2

    enabled: bool = Field(default=True, description="是否启用白名单")
    allowed_users: List[str] = Field(default_factory=list, description="允许使用插件的用户，格式 platform:user_id")
    allowed_groups: List[str] = Field(default_factory=list, description="允许创建群任务的群，格式 platform:group_id")
    allowed_private_users: List[str] = Field(default_factory=list, description="允许作为私聊主动发言目标的用户")


class FrequencyConfig(PluginConfigBase):
    """主动发言频率配置。"""

    __ui_label__ = "频率"
    __ui_icon__ = "activity"
    __ui_order__ = 3

    global_frequency: float = Field(default=1.0, description="全局主动发言密度倍率")
    base_interval_seconds: int = Field(default=3600, description="频率为 1.0 时的基础时间尺度")
    min_interval_seconds: int = Field(default=300, description="同一目标自动主动发起硬间隔")
    max_probability: float = Field(default=0.85, description="单次扫描概率上限")
    history_source_frequency: float = Field(default=0.8, description="聊天历史来源密度倍率")
    memory_source_frequency: float = Field(default=0.8, description="记忆来源密度倍率")
    web_source_frequency: float = Field(default=0.6, description="联网来源密度倍率")
    subscription_source_frequency: float = Field(default=0.7, description="订阅来源密度倍率")
    self_reflection_source_frequency: float = Field(default=0.7, description="自省来源密度倍率")


class TargetConfig(PluginConfigBase):
    """单个聊天目标的自动主动发言配置。"""

    target: str = Field(default="", description="平台目标，格式 platform:group/private:id")
    enabled: bool = Field(default=True, description="是否启用该目标")
    frequency: float = Field(default=1.0, description="该目标主动发言密度倍率")
    quiet_hours_enabled: bool = Field(default=False, description="是否启用安静时段")
    quiet_hours: List[str] = Field(default_factory=list, description="安静时段，例如 00:00-08:00")
    quiet_mode: str = Field(default="block_auto", description="安静时段模式：style_only/reduce/block_auto")
    max_auto_runs_per_day: int = Field(default=6, description="每日自动主动发起次数上限")
    max_schedule_fallbacks_per_day: int = Field(default=6, description="每日日程兜底次数上限")
    enabled_sources: List[str] = Field(
        default_factory=lambda: ["history", "memory", "web", "subscription", "self_reflection"],
        description="自动主动发言来源",
    )
    persona_context_enabled: bool = Field(default=True, description="是否注入插件侧 persona context")


class TavilyConfig(PluginConfigBase):
    """Tavily 联网检索配置。"""

    __ui_label__ = "联网检索"
    __ui_icon__ = "search"
    __ui_order__ = 4

    enabled: bool = Field(default=True, description="是否启用 Tavily 联网检索")
    api_key: str = Field(default="", description="Tavily API Key")
    endpoint: str = Field(default="https://api.tavily.com/search", description="Tavily Search API 地址")
    max_results: int = Field(default=5, description="默认检索结果数")
    search_depth: str = Field(default="basic", description="检索深度")
    include_answer: bool = Field(default=True, description="是否请求 Tavily answer")
    include_raw_content: bool = Field(default=False, description="是否请求原始正文")
    timeout_seconds: int = Field(default=20, description="HTTP 超时时间")


class ConfirmationConfig(PluginConfigBase):
    """二次确认配置。"""

    __ui_label__ = "确认"
    __ui_icon__ = "badge-check"
    __ui_order__ = 5

    pending_ttl_seconds: int = Field(default=300, description="待确认草稿有效期")
    max_pending_per_user: int = Field(default=3, description="单用户最大待确认草稿数")


class ProactiveConfig(PluginConfigBase):
    """Maisaka 主动触发配置。"""

    __ui_label__ = "主动触发"
    __ui_icon__ = "sparkles"
    __ui_order__ = 6

    maisaka_wait_seconds: int = Field(default=90, description="日程主动任务等待 Maisaka 发言秒数")
    fallback_enabled: bool = Field(default=True, description="日程主动任务无发言时是否兜底发送")
    fallback_model_task: str = Field(default="utils", description="兜底发言使用的模型任务")
    fallback_max_tokens: int = Field(default=300, description="兜底发言最大 token")


class SchedulerConfig(PluginConfigBase):
    """调度器配置。"""

    __ui_label__ = "调度器"
    __ui_icon__ = "timer"
    __ui_order__ = 7

    tick_seconds: int = Field(default=20, description="后台调度 tick 间隔")
    auto_scan_seconds: int = Field(default=300, description="自动主动发言扫描间隔")
    history_limit: int = Field(default=30, description="上下文最近消息条数")
    memory_limit: int = Field(default=5, description="长期记忆检索条数")


class AChatterConfig(PluginConfigBase):
    """进阶闲谈家插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)
    whitelist: WhitelistConfig = Field(default_factory=WhitelistConfig)
    frequency: FrequencyConfig = Field(default_factory=FrequencyConfig)
    targets: List[TargetConfig] = Field(default_factory=list)
    tavily: TavilyConfig = Field(default_factory=TavilyConfig)
    confirmation: ConfirmationConfig = Field(default_factory=ConfirmationConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

