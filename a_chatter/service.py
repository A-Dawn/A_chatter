"""A_chatter 共享业务服务。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import random

from .config import AChatterConfig, TargetConfig
from .context_builder import ContextBuilder
from .frequency import compute_trigger_probability, get_source_frequency
from .models import AChatterTask, ChatTarget, RunStatus, ScheduleKind, TaskDraft, TaskStatus, TaskType
from .parser import NaturalLanguageTaskParser, build_parse_context
from .proactive import ProactiveExecutor
from .rbac import RbacService
from .storage import AChatterStorage
from .tavily_client import TavilyClient
from .utils import build_actor, default_target_from_context, extract_llm_response, extract_stream_id, make_id, parse_target, utc_now


class AChatterService:
    """命令、Tool 和后台调度共享的业务门面。"""

    def __init__(self, ctx: Any, config: AChatterConfig, plugin_root: Path) -> None:
        self.ctx = ctx
        self.config = config
        self.storage = AChatterStorage(plugin_root / "data" / "a_chatter.sqlite3")
        self.rbac = RbacService(config)
        self.tavily_client = TavilyClient(config.tavily)
        self.parser = NaturalLanguageTaskParser(ctx)
        self.context_builder = ContextBuilder(ctx, config, self.tavily_client)
        self.proactive = ProactiveExecutor(ctx, config)

    async def start(self) -> None:
        """初始化服务。"""

        await self.storage.initialize()

    def update_config(self, config: AChatterConfig) -> None:
        """热更新配置。"""

        self.config = config
        self.rbac.update_config(config)
        self.tavily_client.update_config(config.tavily)
        self.context_builder.update_config(config)
        self.proactive.update_config(config)

    async def create_draft(self, user_request: str, context: Dict[str, Any]) -> tuple[TaskDraft, str]:
        """创建待确认草稿。"""

        if not self.config.plugin.enabled:
            raise ValueError("A_chatter 当前未启用")
        parse_context = build_parse_context(context)
        draft = await self.parser.parse(user_request, parse_context)
        draft.draft_id = make_id("draft")
        draft.created_at = utc_now()
        draft.expires_at = draft.created_at + timedelta(seconds=self.config.confirmation.pending_ttl_seconds)
        draft.target = await self.resolve_target(draft.target, context)
        permission = self.rbac.can_create_task(parse_context.actor, draft.target)
        if not permission.allowed:
            raise PermissionError(permission.reason)
        await self.storage.save_pending(draft, max_pending_per_user=self.config.confirmation.max_pending_per_user)
        confirmation_text = await self.parser.build_confirmation_text(draft)
        return draft, confirmation_text

    async def confirm_draft(self, context: Dict[str, Any], draft_id: str = "") -> AChatterTask:
        """确认草稿并创建正式任务。"""

        actor = build_actor(context)
        if not actor.subject:
            raise ValueError("无法识别确认用户")
        drafts = await self.storage.list_pending_for_actor(actor.platform, actor.user_id)
        if draft_id:
            draft = next((item for item in drafts if item.draft_id == draft_id), None)
        elif len(drafts) == 1:
            draft = drafts[0]
        elif len(drafts) > 1:
            raise ValueError("你有多个待确认草稿，请使用 `/ac 确认 <草稿ID>` 指定")
        else:
            draft = None
        if draft is None:
            raise ValueError("没有找到可确认的草稿，可能已经过期")
        permission = self.rbac.can_create_task(actor, draft.target)
        if not permission.allowed:
            raise PermissionError(permission.reason)
        return await self.storage.create_task_from_draft(draft)

    async def cancel_draft(self, context: Dict[str, Any], draft_id: str = "") -> str:
        """取消待确认草稿。"""

        actor = build_actor(context)
        drafts = await self.storage.list_pending_for_actor(actor.platform, actor.user_id)
        if draft_id:
            target_draft = next((item for item in drafts if item.draft_id == draft_id), None)
        elif len(drafts) == 1:
            target_draft = drafts[0]
        elif len(drafts) > 1:
            raise ValueError("你有多个待确认草稿，请使用 `/ac 取消 <草稿ID>` 指定")
        else:
            target_draft = None
        if target_draft is None:
            raise ValueError("没有找到可取消的草稿")
        await self.storage.delete_pending(target_draft.draft_id)
        return target_draft.draft_id

    async def list_tasks_for_context(self, context: Dict[str, Any], target_text: str = "") -> List[AChatterTask]:
        """按当前上下文或指定目标列出任务。"""

        actor = build_actor(context)
        target_stream_id = ""
        normalized_target_text = str(target_text or "").strip()
        if not normalized_target_text or normalized_target_text == "当前":
            target_stream_id = actor.stream_id
        else:
            target = parse_target(target_text)
            if target is None:
                raise ValueError("目标格式应为 platform:group/private:id")
            target = await self.resolve_target(target, context)
            target_stream_id = target.stream_id
        tasks = await self.storage.list_tasks(target_stream_id=target_stream_id, limit=50)
        visible_tasks = []
        for task in tasks:
            permission = self.rbac.can_view_task(actor, task)
            if permission.allowed:
                visible_tasks.append(task)
        return visible_tasks

    async def get_task_for_actor(self, context: Dict[str, Any], task_id: str) -> AChatterTask:
        """读取并校验任务查看权限。"""

        actor = build_actor(context)
        task = await self.storage.get_task(task_id)
        if task is None:
            raise ValueError("任务不存在")
        permission = self.rbac.can_view_task(actor, task)
        if not permission.allowed:
            raise PermissionError(permission.reason)
        return task

    async def manage_task(self, context: Dict[str, Any], task_id: str, action: str) -> str:
        """暂停、恢复、删除或立即运行任务。"""

        actor = build_actor(context)
        task = await self.storage.get_task(task_id)
        if task is None:
            raise ValueError("任务不存在")
        permission = self.rbac.can_manage_task(actor, task)
        if not permission.allowed:
            raise PermissionError(permission.reason)

        normalized_action = str(action or "").strip()
        if normalized_action in {"暂停", "pause"}:
            await self.storage.update_task_status(task_id, TaskStatus.PAUSED)
            return "已暂停任务"
        if normalized_action in {"恢复", "resume"}:
            await self.storage.update_task_status(task_id, TaskStatus.ACTIVE)
            return "已恢复任务"
        if normalized_action in {"删除", "delete"}:
            await self.storage.update_task_status(task_id, TaskStatus.DELETED)
            return "已删除任务"
        if normalized_action in {"立即运行", "run"}:
            await self.execute_task(task)
            return "已触发任务执行"
        raise ValueError("不支持的管理动作")

    async def execute_task(self, task: AChatterTask) -> None:
        """执行到期任务。"""

        if task.task_type == TaskType.REMINDER:
            result = await self.ctx.send.text(
                task.content.user_intent,
                task.target.stream_id,
                typing=True,
                storage_message=True,
                sync_to_maisaka_history=True,
                maisaka_source_kind="plugin:a-chatter:reminder",
            )
            success = not (result is False or (isinstance(result, dict) and result.get("success") is False))
            await self.storage.record_run(
                task_id=task.task_id,
                target_stream_id=task.target.stream_id,
                status=RunStatus.SUCCESS.value if success else RunStatus.FAILED.value,
                error="" if success else str(result),
            )
            await self.storage.mark_task_run(task, next_run_at=self.compute_next_run_at(task))
            return

        quiet = self.is_quiet_now(task.target)
        bundle = await self.context_builder.build_for_schedule(task, quiet=quiet)
        run_result = await self.proactive.trigger_schedule(task, bundle)
        await self.storage.record_run(
            task_id=task.task_id,
            target_stream_id=task.target.stream_id,
            status=run_result.status.value,
            used_fallback=run_result.used_fallback,
            error=run_result.error,
            metadata=run_result.metadata,
        )
        await self.storage.mark_task_run(task, next_run_at=self.compute_next_run_at(task))
        state = await self.storage.get_target_state(task.target.stream_id)
        state.last_schedule_run_at = utc_now()
        if run_result.used_fallback:
            state.daily_fallback_count += 1
        await self.storage.update_target_state(state)

    async def scan_auto_targets(self) -> None:
        """扫描配置中的自动主动发起目标。"""

        if not self.config.plugin.enabled:
            return
        for target_config in self.config.targets:
            if not target_config.enabled or not target_config.target.strip():
                continue
            target = parse_target(target_config.target)
            if target is None:
                continue
            target = await self.resolve_target(target, {})
            await self._scan_auto_target(target, target_config)

    async def resolve_target(self, target: ChatTarget, context: Dict[str, Any]) -> ChatTarget:
        """将平台目标解析为真实 stream_id。"""

        if target.stream_id:
            return target
        current_target = default_target_from_context(context) if context else None
        if current_target is not None and target.key == current_target.key and current_target.stream_id:
            return ChatTarget(target.platform, target.chat_type, target.target_id, current_target.stream_id)
        if target.chat_type == "group":
            stream = await self.ctx.chat.get_stream_by_group_id(target.target_id, platform=target.platform)
        else:
            stream = await self.ctx.chat.get_stream_by_user_id(target.target_id, platform=target.platform)
        stream_id = extract_stream_id(stream)
        if not stream_id:
            raise ValueError(f"未找到目标聊天流：{target.key}，请先让 Bot 与该目标建立会话")
        return ChatTarget(target.platform, target.chat_type, target.target_id, stream_id)

    def compute_next_run_at(self, task: AChatterTask) -> Optional[datetime]:
        """计算下一次运行时间。"""

        now = utc_now()
        if task.schedule.kind == ScheduleKind.ONCE:
            return None
        if task.schedule.kind == ScheduleKind.INTERVAL:
            return now + timedelta(seconds=task.schedule.interval_seconds)
        if task.schedule.kind == ScheduleKind.CRON:
            try:
                from croniter import croniter
            except ImportError as exc:
                raise RuntimeError("croniter 未安装，无法计算 cron 任务下一次运行时间") from exc
            return croniter(task.schedule.cron, now).get_next(datetime).astimezone(timezone.utc)
        return None

    def is_quiet_now(self, target: ChatTarget) -> bool:
        """判断目标当前是否处于安静时段。"""

        target_config = self.find_target_config(target)
        if target_config is None or not target_config.quiet_hours_enabled:
            return False
        now_text = datetime.now().strftime("%H:%M")
        for quiet_range in target_config.quiet_hours:
            if self._time_in_range(now_text, quiet_range):
                return True
        return False

    def find_target_config(self, target: ChatTarget) -> Optional[TargetConfig]:
        """查找目标配置。"""

        return next((item for item in self.config.targets if item.target == target.key), None)

    def query_status(self, context: Dict[str, Any], scope: str = "status") -> str:
        """生成插件状态文本。"""

        actor = build_actor(context)
        if scope in {"权限", "permission", "permissions"}:
            return self.rbac.describe_actor_permissions(actor)
        if scope in {"检索", "检索状态", "tavily", "web"}:
            return (
                "Tavily 检索状态："
                f"{'可用' if self.tavily_client.is_available() else '不可用'}\n"
                f"enabled={self.config.tavily.enabled}，api_key={'已配置' if self.config.tavily.api_key.strip() else '未配置'}"
            )
        if scope in {"频率", "frequency"}:
            return (
                "频率配置：\n"
                f"global_frequency={self.config.frequency.global_frequency}\n"
                f"base_interval_seconds={self.config.frequency.base_interval_seconds}\n"
                f"min_interval_seconds={self.config.frequency.min_interval_seconds}"
            )
        return (
            f"A_chatter 状态：{'启用' if self.config.plugin.enabled else '停用'}\n"
            f"配置版本：{self.config.plugin.config_version}\n"
            f"自动扫描目标数：{len(self.config.targets)}"
        )

    async def _scan_auto_target(self, target: ChatTarget, target_config: TargetConfig) -> None:
        state = await self.storage.get_target_state(target.stream_id)
        today = utc_now().strftime("%Y-%m-%d")
        if state.date_key != today:
            state.date_key = today
            state.daily_auto_count = 0
            state.daily_fallback_count = 0
        if state.daily_auto_count >= max(0, int(target_config.max_auto_runs_per_day)):
            await self.storage.update_target_state(state)
            return

        for source in target_config.enabled_sources:
            normalized_source = str(source or "").strip()
            if normalized_source not in {"history", "memory", "web", "subscription", "self_reflection"}:
                continue
            quiet_factor = self._quiet_factor_for_auto(target_config)
            elapsed_seconds = self._elapsed_since(state.last_auto_run_at)
            probability = compute_trigger_probability(
                global_frequency=self.config.frequency.global_frequency,
                target_frequency=target_config.frequency,
                source_frequency=get_source_frequency(normalized_source, self.config.frequency),
                quiet_factor=quiet_factor,
                elapsed_seconds=elapsed_seconds,
                base_interval_seconds=self.config.frequency.base_interval_seconds,
                min_interval_seconds=self.config.frequency.min_interval_seconds,
                max_probability=self.config.frequency.max_probability,
                intent_score=1.0,
            )
            if probability <= 0 or random.random() > probability:
                continue
            await self._judge_and_trigger_auto(target, normalized_source, state)
            break
        await self.storage.update_target_state(state)

    async def _judge_and_trigger_auto(self, target: ChatTarget, source: str, state: Any) -> None:
        preliminary = await self.context_builder.build_preliminary_for_auto(target, source)
        prompt = (
            "你是 A_chatter 自动主动发起判断器。请输出严格 JSON。\n"
            "普通 source 的发起理由必须来自聊天历史、记忆、联网或订阅等明确锚点；"
            "只有 self_reflection 可以由 persona context 驱动候选意图。\n\n"
            f"{preliminary}\n\n"
            "输出格式："
            "{\"should_speak\": true, \"intent_score\": 0.0, \"reason\": \"\", "
            "\"intent_kind\": \"history|memory|web|subscription|self_reflection\", "
            "\"topic\": \"\", \"style_hint\": \"\"}"
        )
        result = await self.ctx.llm.generate(prompt=prompt, model="utils", temperature=0.2, max_tokens=800)
        text = extract_llm_response(result)
        decision = self._parse_auto_decision(text)
        if not bool(decision.get("should_speak")):
            await self.storage.record_run(
                task_id=f"auto:{source}",
                target_stream_id=target.stream_id,
                status=RunStatus.SKIPPED.value,
                metadata={"reason": decision.get("reason", ""), "source": source},
            )
            return

        elapsed_seconds = self._elapsed_since(state.last_auto_run_at)
        target_config = self.find_target_config(target) or TargetConfig(target=target.key)
        final_probability = compute_trigger_probability(
            global_frequency=self.config.frequency.global_frequency,
            target_frequency=target_config.frequency,
            source_frequency=get_source_frequency(source, self.config.frequency),
            quiet_factor=self._quiet_factor_for_auto(target_config),
            elapsed_seconds=elapsed_seconds,
            base_interval_seconds=self.config.frequency.base_interval_seconds,
            min_interval_seconds=self.config.frequency.min_interval_seconds,
            max_probability=self.config.frequency.max_probability,
            intent_score=float(decision.get("intent_score") or 0.0),
        )
        if final_probability <= 0 or random.random() > final_probability:
            await self.storage.record_run(
                task_id=f"auto:{source}",
                target_stream_id=target.stream_id,
                status=RunStatus.SKIPPED.value,
                metadata={"reason": "final_frequency_gate", "source": source, "probability": final_probability},
            )
            return

        topic = str(decision.get("topic") or decision.get("reason") or source).strip()
        bundle = await self.context_builder.build_for_auto(
            target,
            source,
            topic,
            style_hint=str(decision.get("style_hint") or ""),
        )
        run_result = await self.proactive.trigger_auto(target.stream_id, bundle)
        await self.storage.record_run(
            task_id=f"auto:{source}",
            target_stream_id=target.stream_id,
            status=run_result.status.value,
            error=run_result.error,
            metadata={**run_result.metadata, "source": source},
        )
        if run_result.success:
            state.last_auto_run_at = utc_now()
            state.daily_auto_count += 1

    @staticmethod
    def _parse_auto_decision(text: str) -> Dict[str, Any]:
        import json
        import re

        raw = str(text or "").strip()
        match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        if match is not None:
            raw = match.group(1).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end >= start:
            raw = raw[start : end + 1]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {"should_speak": False, "reason": "LLM 判断结果不是 JSON", "intent_score": 0.0}
        return data if isinstance(data, dict) else {"should_speak": False, "intent_score": 0.0}

    @staticmethod
    def _elapsed_since(value: Optional[datetime]) -> float:
        if value is None:
            return 10**9
        return max(0.0, (utc_now() - value).total_seconds())

    def _quiet_factor_for_auto(self, target_config: TargetConfig) -> float:
        if not target_config.quiet_hours_enabled:
            return 1.0
        now_text = datetime.now().strftime("%H:%M")
        if not any(self._time_in_range(now_text, item) for item in target_config.quiet_hours):
            return 1.0
        if target_config.quiet_mode == "block_auto":
            return 0.0
        if target_config.quiet_mode == "reduce":
            return 0.2
        return 1.0

    @staticmethod
    def _time_in_range(now_text: str, quiet_range: str) -> bool:
        parts = [part.strip() for part in str(quiet_range or "").split("-", maxsplit=1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return False
        start, end = parts
        if start <= end:
            return start <= now_text <= end
        return now_text >= start or now_text <= end


def format_task_summary(task: AChatterTask) -> str:
    """格式化单个任务摘要。"""

    next_run = task.next_run_at.isoformat() if task.next_run_at else "无"
    return (
        f"{task.task_id} | {task.task_type.value} | {task.title} | "
        f"{task.status.value} | {task.target.key} | 下次：{next_run}"
    )
