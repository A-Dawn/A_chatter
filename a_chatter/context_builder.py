"""A_chatter 主动发言上下文构建。"""

from typing import Any, List

from .config import AChatterConfig, TargetConfig
from .models import AChatterTask, ChatTarget, ContextBundle, TavilyResult
from .tavily_client import TavilyClient, TavilyConfigError
from .utils import extract_llm_response, extract_messages, extract_readable_text


class ContextBuilder:
    """收集 history、memory、web 与 persona context。"""

    def __init__(self, ctx: Any, config: AChatterConfig, tavily_client: TavilyClient) -> None:
        self._ctx = ctx
        self._config = config
        self._tavily_client = tavily_client

    def update_config(self, config: AChatterConfig) -> None:
        """更新配置引用。"""

        self._config = config

    async def build_for_schedule(self, task: AChatterTask, *, quiet: bool = False) -> ContextBundle:
        """构建日程主动任务上下文。"""

        history_text = await self._build_history_text(task.target.stream_id)
        memory_text = await self._build_memory_text(task.content.memory_query or task.content.user_intent)
        web_text = ""
        if task.content.requires_web or task.content.web_query:
            web_text = await self._build_web_fact_text(task.content.web_query or task.content.user_intent)

        quiet_text = ""
        if quiet:
            quiet_text = (
                "\n[安静时段]\n"
                "当前处于该聊天流配置的安静时段。本次是日程驱动任务，仍然需要发言。\n"
                "请只让安静时段影响表达风格：更轻、更短、更克制，不要因此放弃发言。\n"
            )
        persona_text = self._build_persona_context(task.target)
        visible_text = (
            "[A_chatter 日程主动任务]\n"
            f"任务标题：{task.title}\n"
            f"任务类型：{task.task_type.value}\n"
            f"触发原因：日程到点\n"
            f"目标聊天：{task.target.key}\n"
            f"是否必须发言：{'是' if task.content.must_say else '否'}\n"
            f"用户原始意图：{task.content.user_intent}\n"
            f"表达提示：{task.content.style_hint or '无'}\n"
            f"{quiet_text}\n"
            f"{persona_text}\n"
            f"{history_text}\n"
            f"{memory_text}\n"
            f"{web_text}"
        ).strip()
        intent = (
            f"这是 A_chatter 的日程驱动主动任务：请围绕“{task.content.user_intent}”在当前聊天流中自然发言。"
        )
        if task.content.must_say:
            intent += " 本任务必须产生发言；如果当前是安静时段，只让它影响语气，不要放弃发言。"
        return ContextBundle(
            visible_text=visible_text,
            intent=intent,
            reason=f"A_chatter 日程任务到点：{task.title}",
            metadata={"task_id": task.task_id, "task_type": task.task_type.value},
        )

    async def build_for_auto(self, target: ChatTarget, source: str, topic: str, style_hint: str = "") -> ContextBundle:
        """构建自动主动发起上下文。"""

        history_text = await self._build_history_text(target.stream_id)
        memory_text = await self._build_memory_text(topic)
        web_text = ""
        if source in {"web", "subscription"}:
            web_text = await self._build_web_fact_text(topic)
        persona_text = self._build_persona_context(target)
        visible_text = (
            "[A_chatter 自动主动发起]\n"
            f"来源：{source}\n"
            f"目标聊天：{target.key}\n"
            f"候选话题：{topic}\n"
            f"表达提示：{style_hint or '无'}\n\n"
            f"{persona_text}\n"
            f"{history_text}\n"
            f"{memory_text}\n"
            f"{web_text}"
        ).strip()
        intent = f"这是 A_chatter 的自动主动发起：如果自然，请围绕“{topic}”在当前聊天流中发言。"
        return ContextBundle(
            visible_text=visible_text,
            intent=intent,
            reason=f"A_chatter 自动主动发起：{source}",
            metadata={"source": source, "topic": topic},
        )

    async def build_preliminary_for_auto(self, target: ChatTarget, source: str) -> str:
        """构建自动发起判断用轻量上下文。"""

        history_text = await self._build_history_text(target.stream_id, limit=10)
        persona_text = self._build_persona_context(target)
        return (
            "[A_chatter 自动发起判断材料]\n"
            f"来源：{source}\n"
            f"目标聊天：{target.key}\n\n"
            f"{persona_text}\n"
            f"{history_text}"
        ).strip()

    async def _build_history_text(self, stream_id: str, *, limit: int | None = None) -> str:
        if not stream_id:
            return "[最近聊天]\n未能确定目标聊天流。\n"
        recent = await self._ctx.message.get_recent(stream_id, limit=limit or self._config.scheduler.history_limit)
        messages = extract_messages(recent)
        readable = await self._ctx.message.build_readable(messages, timestamp_mode="relative", truncate=True)
        text = extract_readable_text(readable).strip()
        return f"[最近聊天]\n{text or '暂无可用聊天记录'}\n"

    async def _build_memory_text(self, query: str) -> str:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "[长期记忆]\n未提供检索主题。\n"
        result = await self._ctx.knowledge.search(normalized_query, limit=self._config.scheduler.memory_limit)
        if isinstance(result, dict):
            text = str(result.get("content") or result.get("text") or result.get("result") or "").strip()
        else:
            text = str(result or "").strip()
        return f"[长期记忆]\n{text or '没有检索到相关记忆'}\n"

    async def _build_web_fact_text(self, query: str) -> str:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "[联网事实]\n未提供检索查询。\n"
        try:
            results = await self._tavily_client.search(normalized_query)
        except TavilyConfigError as exc:
            return f"[联网事实]\n联网检索未执行：{exc}\n"
        if not results:
            return "[联网事实]\n未检索到可用结果。\n"
        return await self._summarize_web_results(normalized_query, results)

    async def _summarize_web_results(self, query: str, results: List[TavilyResult]) -> str:
        source_lines = []
        for index, result in enumerate(results, start=1):
            source_lines.append(
                f"{index}. 标题：{result.title}\nURL：{result.url}\n摘要：{result.snippet or result.content[:500]}"
            )
        prompt = (
            "你是 A_chatter 的联网检索事实压缩器。请根据 Tavily 结果提取 3 到 7 条事实，"
            "保留来源 URL，标注不确定信息，不要生成最终聊天话术。\n\n"
            f"查询：{query}\n\n"
            + "\n\n".join(source_lines)
        )
        result = await self._ctx.llm.generate(prompt=prompt, model="utils", temperature=0.2, max_tokens=900)
        text = extract_llm_response(result).strip()
        if text:
            return f"[联网检索事实包]\n查询：{query}\n{text}\n"
        fallback_lines = [f"- {item.title}\n  来源：{item.url}" for item in results]
        return f"[联网检索事实包]\n查询：{query}\n" + "\n".join(fallback_lines) + "\n"

    def _build_persona_context(self, target: ChatTarget) -> str:
        target_config = self._find_target_config(target)
        if target_config is not None and not target_config.persona_context_enabled:
            return "[Persona Context]\n该目标配置未启用插件侧 persona context。\n"
        return (
            "[Persona Context]\n"
            "A_chatter 只提供事实、时机和任务边界；最终表达仍交给 Maisaka 人设完成。\n"
            "请自然衔接当前关系，不要暴露插件、调度器、检索流程等内部信息。\n"
        )

    def _find_target_config(self, target: ChatTarget) -> TargetConfig | None:
        for item in self._config.targets:
            if item.target == target.key:
                return item
        return None

