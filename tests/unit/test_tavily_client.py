"""A_chatter Tavily 客户端测试。"""

from a_chatter.tavily_client import TavilyClient


def test_normalize_response_dedupes_urls() -> None:
    results = TavilyClient.normalize_response(
        {
            "results": [
                {"title": "A", "url": "https://example.com/a", "content": "alpha"},
                {"title": "A2", "url": "https://example.com/a", "content": "duplicate"},
                {"title": "B", "url": "https://example.com/b", "snippet": "beta"},
                {"title": "No URL", "content": "skip"},
            ]
        }
    )

    assert [item.url for item in results] == ["https://example.com/a", "https://example.com/b"]
    assert results[0].snippet == "alpha"

