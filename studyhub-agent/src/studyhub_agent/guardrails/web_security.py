from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

AddressResolver = Callable[[str], Iterable[str]]


class UnsafeUrlError(ValueError):
    """A URL the agent may not fetch."""


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


@dataclass(frozen=True, slots=True)
class WebSecurityPolicy:
    max_urls_per_call: int = 3
    allowed_ports: tuple[int | None, ...] = (None, 80, 443)

    def validate_url(self, url: str, *, resolver: AddressResolver) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise UnsafeUrlError("only http and https URLs are allowed")
        if not parsed.hostname or parsed.username or parsed.password:
            raise UnsafeUrlError("URL must contain a plain hostname")
        try:
            port = parsed.port
        except ValueError as error:
            raise UnsafeUrlError("invalid port") from error
        if port not in self.allowed_ports:
            raise UnsafeUrlError("non-standard ports are blocked")
        try:
            addresses = [str(ipaddress.ip_address(parsed.hostname))]
        except ValueError:
            addresses = list(resolver(parsed.hostname))
        if not addresses or not all(_is_public(address) for address in addresses):
            raise UnsafeUrlError("URL resolves to a non-public address")
        return url
