"""Short-lived, single-use credentials for browser WebSocket handshakes."""
from __future__ import annotations

import secrets
import threading
import time
from typing import Callable


class OneTimeTicketStore:
    def __init__(
        self,
        ttl_seconds: int = 45,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.ttl_seconds = max(5, min(int(ttl_seconds), 300))
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._tickets: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: str) -> str:
        owner = str(user_id or "").strip()
        if not owner:
            raise ValueError("Un utilisateur est requis pour émettre un ticket.")
        now = self._clock()
        with self._lock:
            self._tickets = {
                key: value for key, value in self._tickets.items()
                if value[1] > now
            }
            ticket = self._token_factory()
            while ticket in self._tickets:
                ticket = self._token_factory()
            self._tickets[ticket] = (owner, now + self.ttl_seconds)
        return ticket

    def consume(self, ticket: str) -> str | None:
        key = str(ticket or "").strip()
        if not key:
            return None
        now = self._clock()
        with self._lock:
            value = self._tickets.pop(key, None)
        if value is None or value[1] <= now:
            return None
        return value[0]
