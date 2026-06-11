"""A_chatter RBAC 与白名单判断。"""

from typing import Iterable, Set

from .config import AChatterConfig
from .models import AChatterTask, Actor, ChatTarget, PermissionResult


class RbacService:
    """权限判断服务。"""

    def __init__(self, config: AChatterConfig) -> None:
        self._config = config

    def update_config(self, config: AChatterConfig) -> None:
        """更新配置引用。"""

        self._config = config

    def can_create_task(self, actor: Actor, target: ChatTarget) -> PermissionResult:
        """判断用户是否可以创建目标任务。"""

        if not actor.subject:
            return PermissionResult(False, "无法识别用户身份")
        if self._is_super_admin(actor):
            return PermissionResult(True)
        if not self._is_actor_whitelisted(actor):
            return PermissionResult(False, "当前用户不在 A_chatter 白名单中")
        if not self._is_target_whitelisted(target):
            return PermissionResult(False, "目标聊天不在 A_chatter 白名单中")

        is_cross_stream = bool(actor.stream_id and target.stream_id and actor.stream_id != target.stream_id)
        if is_cross_stream and not self._config.permissions.allow_cross_stream_by_default:
            return PermissionResult(False, "没有跨聊天流创建任务权限")

        if target.chat_type == "private" and self._config.permissions.default_allow_private_schedule:
            if target.target_id == actor.user_id or self._config.permissions.allow_cross_stream_by_default:
                return PermissionResult(True)
            return PermissionResult(False, "普通用户只能为自己的私聊创建任务")

        if target.chat_type == "group" and self._config.permissions.default_allow_group_schedule:
            return PermissionResult(True)

        return PermissionResult(False, "当前配置不允许普通用户为该目标创建任务")

    def can_view_task(self, actor: Actor, task: AChatterTask) -> PermissionResult:
        """判断用户是否可以查看任务。"""

        if self._is_super_admin(actor):
            return PermissionResult(True)
        if actor.user_id == task.creator_user_id and actor.platform == task.creator_platform:
            return PermissionResult(True)
        if actor.stream_id and actor.stream_id == task.target.stream_id:
            return PermissionResult(True)
        return PermissionResult(False, "没有查看该任务的权限")

    def can_manage_task(self, actor: Actor, task: AChatterTask) -> PermissionResult:
        """判断用户是否可以管理任务。"""

        if self._is_super_admin(actor):
            return PermissionResult(True)
        if actor.user_id == task.creator_user_id and actor.platform == task.creator_platform:
            return PermissionResult(True)
        return PermissionResult(False, "没有管理该任务的权限")

    def describe_actor_permissions(self, actor: Actor) -> str:
        """生成用户权限状态说明。"""

        roles = []
        if self._is_super_admin(actor):
            roles.append("super_admin")
        if self._is_actor_whitelisted(actor):
            roles.append("trusted_user")
        if not roles:
            roles.append("normal_user")
        return f"用户：{actor.subject or '未知'}\n角色：{', '.join(roles)}"

    def _is_super_admin(self, actor: Actor) -> bool:
        return actor.subject in self._normalize_set(self._config.permissions.super_admins)

    def _is_actor_whitelisted(self, actor: Actor) -> bool:
        if not self._config.whitelist.enabled:
            return True
        allowed_users = self._normalize_set(self._config.whitelist.allowed_users)
        if not allowed_users:
            return True
        return actor.subject in allowed_users or self._is_super_admin(actor)

    def _is_target_whitelisted(self, target: ChatTarget) -> bool:
        if not self._config.whitelist.enabled:
            return True
        if target.chat_type == "group":
            allowed_groups = self._normalize_set(self._config.whitelist.allowed_groups)
            if not allowed_groups:
                return True
            return f"{target.platform}:{target.target_id}" in allowed_groups
        allowed_private_users = self._normalize_set(self._config.whitelist.allowed_private_users)
        if not allowed_private_users:
            return True
        return f"{target.platform}:{target.target_id}" in allowed_private_users

    @staticmethod
    def _normalize_set(values: Iterable[str]) -> Set[str]:
        return {str(value or "").strip().lower() for value in values if str(value or "").strip()}
