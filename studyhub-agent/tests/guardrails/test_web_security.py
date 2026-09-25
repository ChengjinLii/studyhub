import pytest

from studyhub_agent.guardrails.web_security import UnsafeUrlError, WebSecurityPolicy

POLICY = WebSecurityPolicy()


def _public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _private(_host: str) -> list[str]:
    return ["10.0.0.8"]


def test_public_https_url_is_allowed() -> None:
    assert POLICY.validate_url("https://example.com/a", resolver=_public) == "https://example.com/a"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "http://user:pw@example.com",
        "http://example.com:8080",
        "http://127.0.0.1/",
        "https:///nohost",
    ],
)
def test_unsafe_urls_are_rejected(url) -> None:
    with pytest.raises(UnsafeUrlError):
        POLICY.validate_url(url, resolver=_public)


def test_hostname_resolving_to_private_address_is_rejected() -> None:
    with pytest.raises(UnsafeUrlError, match="non-public"):
        POLICY.validate_url("https://intranet.example.com", resolver=_private)
