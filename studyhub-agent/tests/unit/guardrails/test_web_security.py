import asyncio

import pytest

from studyhub_agent.guardrails.web_security import UnsafeUrlError, WebSecurityPolicy


def test_web_guard_blocks_non_http_local_private_and_nonstandard_ports() -> None:
    policy = WebSecurityPolicy()

    for url in (
        "file:///etc/passwd",
        "http://127.0.0.1/private",
        "http://10.0.0.8/private",
        "http://[::1]/private",
        "https://example.com:8443/private",
    ):
        with pytest.raises(UnsafeUrlError):
            policy.validate_url(url)


def test_web_guard_blocks_dns_rebinding_to_private_address() -> None:
    policy = WebSecurityPolicy()
    with pytest.raises(UnsafeUrlError):
        policy.validate_url("https://public-looking.example/path", resolver=lambda _: ["192.168.1.5"])


def test_guarded_fixture_search_filters_unsafe_results_and_fetches_safe_page(web) -> None:
    results = asyncio.run(web.search("通信原理 复习", limit=10))
    fetched = asyncio.run(web.fetch("https://docs.example.edu/communications/review"))

    assert [result["url"] for result in results] == ["https://docs.example.edu/communications/review"]
    assert fetched is not None
    assert "知识框架" in fetched["content"]


def test_response_limits_are_enforced() -> None:
    policy = WebSecurityPolicy(max_redirects=1, max_response_bytes=10)
    with pytest.raises(UnsafeUrlError):
        policy.validate_response(content_type="text/html", response_bytes=11, redirects=0)
    with pytest.raises(UnsafeUrlError):
        policy.validate_response(content_type="application/octet-stream", response_bytes=1, redirects=0)
    with pytest.raises(UnsafeUrlError):
        policy.validate_response(content_type="text/plain", response_bytes=1, redirects=2)
