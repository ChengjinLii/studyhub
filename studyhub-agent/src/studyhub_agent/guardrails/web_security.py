from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_CONTENT_TYPES = frozenset({"text/html", "text/plain", "application/json", "application/xhtml+xml"})


class UnsafeUrlError(ValueError):
    pass


AddressResolver = Callable[[str], Iterable[str]]


def system_resolver(hostname: str) -> list[str]:
    return list({item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)})


def _is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


@dataclass(frozen=True, slots=True)
class WebSecurityPolicy:
    max_redirects: int = 3
    max_response_bytes: int = 1_000_000
    allowed_content_types: frozenset[str] = ALLOWED_CONTENT_TYPES

    def __post_init__(self) -> None:
        if self.max_redirects < 0 or self.max_response_bytes < 1:
            raise ValueError("web limits must be non-negative")

    def validate_url(self, url: str, *, resolver: AddressResolver = system_resolver) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeUrlError("only http and https URLs are allowed")
        if not parsed.hostname or parsed.username or parsed.password:
            raise UnsafeUrlError("URL must contain a plain public hostname")
        if parsed.port not in {None, 80, 443}:
            raise UnsafeUrlError("non-standard web ports are blocked")
        try:
            addresses = [str(ipaddress.ip_address(parsed.hostname))]
        except ValueError:
            addresses = list(resolver(parsed.hostname))
        if not addresses or any(not _is_public_address(address) for address in addresses):
            raise UnsafeUrlError("URL resolves to a non-public address")
        return url

    def validate_response(self, *, content_type: str, response_bytes: int, redirects: int) -> None:
        normalized_type = content_type.split(";", 1)[0].strip().lower()
        if redirects > self.max_redirects:
            raise UnsafeUrlError("redirect limit exceeded")
        if response_bytes > self.max_response_bytes:
            raise UnsafeUrlError("response size limit exceeded")
        if normalized_type not in self.allowed_content_types:
            raise UnsafeUrlError(f"content type is not allowed: {normalized_type}")
