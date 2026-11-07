"""Explicitly configured HTTPS webhook adapter for outbound channel commands.

This is a provider-neutral integration seam, not an email/SMS gateway. A 2xx
only means accepted by the configured adapter; delivery requires a receipt.
Network-uncertain submissions are never automatically replayed.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from typing import Any


class ChannelConfigurationError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


class ChannelWebhook:
    def __init__(self, url: str, token: str, allowed_hosts: set[str]):
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or not host or host not in allowed_hosts
                or parsed.username or parsed.password or parsed.fragment or
                parsed.port not in (None, 443)):
            raise ChannelConfigurationError(
                "channel webhook requires a trusted HTTPS host on the explicit allowlist"
            )
        if not token or len(token) < 16:
            raise ChannelConfigurationError("channel webhook token is not configured")
        self.url = url
        self.token = token

    @classmethod
    def from_environment(cls) -> "ChannelWebhook":
        allowed = {
            value.strip().lower()
            for value in os.getenv("GROWTHEVO_CHANNEL_ALLOWED_HOSTS", "").split(",")
            if value.strip()
        }
        return cls(
            url=os.getenv("GROWTHEVO_CHANNEL_WEBHOOK_URL", ""),
            token=os.getenv("GROWTHEVO_CHANNEL_WEBHOOK_TOKEN", ""),
            allowed_hosts=allowed,
        )

    def submit(self, command: dict[str, Any]) -> bool:
        body = json.dumps(command, sort_keys=True, separators=(",", ":")).encode()
        request = Request(
            self.url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.token,
                "Idempotency-Key": command["idempotency_key"],
            },
        )
        try:
            with build_opener(_NoRedirect()).open(request, timeout=5) as response:
                return 200 <= response.status < 300
        except (HTTPError, URLError, TimeoutError, OSError):
            return False
