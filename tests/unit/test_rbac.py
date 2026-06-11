"""A_chatter RBAC 测试。"""

from a_chatter.config import AChatterConfig
from a_chatter.models import Actor, ChatTarget
from a_chatter.rbac import RbacService


def test_super_admin_can_create_cross_stream_task() -> None:
    config = AChatterConfig()
    config.permissions.super_admins = ["qq:10000"]
    service = RbacService(config)

    result = service.can_create_task(
        Actor(platform="qq", user_id="10000", stream_id="stream_a"),
        ChatTarget(platform="qq", chat_type="group", target_id="123", stream_id="stream_b"),
    )

    assert result.allowed is True


def test_default_config_allows_private_self_task() -> None:
    config = AChatterConfig()
    service = RbacService(config)

    result = service.can_create_task(
        Actor(platform="qq", user_id="10000", stream_id="stream_a"),
        ChatTarget(platform="qq", chat_type="private", target_id="10000", stream_id="stream_a"),
    )

    assert result.allowed is True


def test_non_empty_whitelist_rejects_unlisted_user() -> None:
    config = AChatterConfig()
    config.whitelist.allowed_users = ["qq:20000"]
    service = RbacService(config)

    result = service.can_create_task(
        Actor(platform="qq", user_id="10000", stream_id="stream_a"),
        ChatTarget(platform="qq", chat_type="private", target_id="10000", stream_id="stream_a"),
    )

    assert result.allowed is False
    assert "白名单" in result.reason


def test_whitelisted_user_can_create_private_self_task() -> None:
    config = AChatterConfig()
    config.whitelist.allowed_users = ["qq:10000"]
    config.whitelist.allowed_private_users = ["qq:10000"]
    service = RbacService(config)

    result = service.can_create_task(
        Actor(platform="qq", user_id="10000", stream_id="stream_a"),
        ChatTarget(platform="qq", chat_type="private", target_id="10000", stream_id="stream_a"),
    )

    assert result.allowed is True
