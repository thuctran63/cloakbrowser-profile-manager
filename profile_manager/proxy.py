"""Proxy parsing, validation, and redaction helpers."""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

_ALLOWED_SCHEMES = {"http", "https", "socks5", "socks5h"}


def normalize_proxy(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None

    parsed = urlsplit(value)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError("Proxy phải bắt đầu bằng http://, https://, socks5:// hoặc socks5h://")
    if not parsed.hostname:
        raise ValueError("Proxy thiếu hostname")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Port proxy không hợp lệ") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("Proxy cần port từ 1 đến 65535")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Proxy không được chứa path, query hoặc fragment")
    return value


def mask_proxy(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        credentials = ""
        if parsed.username is not None:
            credentials = f"{parsed.username}:***@"
        port = f":{parsed.port}" if parsed.port else ""
        return urlunsplit((parsed.scheme, f"{credentials}{host}{port}", "", "", ""))
    except (ValueError, TypeError):
        return "Proxy không hợp lệ"


def redact_proxy_in_text(text: str, proxy: str | None) -> str:
    if not proxy:
        return text
    redacted = text.replace(proxy, mask_proxy(proxy))
    try:
        parsed = urlsplit(proxy)
        secrets = [value for value in (parsed.username, parsed.password) if value]
        for secret in secrets:
            for variant in {secret, unquote(secret), quote(unquote(secret), safe="")}:
                if variant:
                    redacted = redacted.replace(variant, "***")
    except (TypeError, ValueError):
        pass
    return re.sub(
        r"(?i)(https?|socks5h?)://([^/@\s:]+):([^@/\s]+)@",
        r"\1://***:***@",
        redacted,
    )
