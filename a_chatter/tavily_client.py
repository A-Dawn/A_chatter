"""Tavily 联网检索客户端。"""

from typing import Any, Dict, List

import httpx

from .config import TavilyConfig
from .models import TavilyResult


class TavilyConfigError(RuntimeError):
    """Tavily 配置错误。"""


class TavilyClient:
    """Tavily Search API 客户端。"""

    def __init__(self, config: TavilyConfig) -> None:
        self._config = config

    def update_config(self, config: TavilyConfig) -> None:
        """更新 Tavily 配置。"""

        self._config = config

    def is_available(self) -> bool:
        """判断 Tavily 是否具备调用条件。"""

        return bool(self._config.enabled and self._config.api_key.strip())

    async def search(self, query: str, *, max_results: int | None = None) -> List[TavilyResult]:
        """执行 Tavily 检索并归一化结果。"""

        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("Tavily 查询不能为空")
        if not self._config.enabled:
            raise TavilyConfigError("Tavily 联网检索未启用")
        api_key = self._config.api_key.strip()
        if not api_key:
            raise TavilyConfigError("Tavily API Key 未配置")

        payload = {
            "api_key": api_key,
            "query": normalized_query,
            "search_depth": self._config.search_depth,
            "include_answer": self._config.include_answer,
            "include_raw_content": self._config.include_raw_content,
            "max_results": max_results or self._config.max_results,
        }
        async with httpx.AsyncClient(timeout=float(self._config.timeout_seconds)) as client:
            response = await client.post(self._config.endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
        return self.normalize_response(data)

    @staticmethod
    def normalize_response(data: Dict[str, Any]) -> List[TavilyResult]:
        """归一化 Tavily 响应。"""

        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            return []

        seen_urls: set[str] = set()
        results: List[TavilyResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                TavilyResult(
                    title=title or url,
                    url=url,
                    snippet=str(item.get("snippet") or item.get("content") or "").strip(),
                    content=str(item.get("raw_content") or item.get("content") or "").strip(),
                    published_at=str(item.get("published_at") or "").strip(),
                )
            )
        return results

