from __future__ import annotations

from typing import Any, Callable, MutableMapping
import time
import queue


class DummyServerInterface:
    """Placeholder client for vrtrainer.online until the real API exists.

    The trainer runtime can call ``send_settings``, ``send_command``, or
    ``send_scold`` and poll the resulting stub acknowledgements with
    ``poll_events``. No network traffic occurs; everything is kept
    in-memory so other components can be wired up without the server.
    """

    def __init__(
        self,
        *,
        role: str = "trainer",
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._role = "trainer" if role == "trainer" else "pet"
        self._log = log
        self._connected = False

        self._outgoing: list[dict[str, Any]] = []
        self._incoming: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self._latest_settings: dict[str, Any] = {}

    # Lifecycle -------------------------------------------------------
    def start(self) -> None:
        self._connected = True
        self._log_message("dummy server started")

    def stop(self) -> None:
        self._connected = False
        self._log_message("dummy server stopped")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # Trainer → server stubs -----------------------------------------
    def send_settings(self, settings: MutableMapping[str, Any]) -> None:
        """Record trainer settings and queue a stub acknowledgement."""
        data = dict(settings)
        self._latest_settings = data
        payload = {"type": "settings", "data": data}
        self._record_outgoing(payload)
        self._enqueue_ack(payload)

    def send_command(self, phrase: str, metadata: MutableMapping[str, Any] | None = None) -> None:
        """Record a trainer-issued command phrase."""
        payload = {"type": "command", "phrase": phrase, "meta": dict(metadata or {})}
        self._record_outgoing(payload)
        self._enqueue_ack(payload)

    def send_scold(self, phrase: str, metadata: MutableMapping[str, Any] | None = None) -> None:
        """Record a trainer scolding phrase."""
        payload = {"type": "scold", "phrase": phrase, "meta": dict(metadata or {})}
        self._record_outgoing(payload)
        self._enqueue_ack(payload)

    # Server → trainer polling ---------------------------------------
    def poll_events(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return up to ``limit`` queued acknowledgements."""
        events: list[dict[str, Any]] = []
        while not self._incoming.empty() and len(events) < limit:
            events.append(self._incoming.get_nowait())
        return events

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Fetch the most recent setting pushed by the trainer."""
        return self._latest_settings.get(key, default)

    @property
    def latest_settings(self) -> dict[str, Any]:
        return dict(self._latest_settings)

    # Internal helpers -----------------------------------------------
    def _record_outgoing(self, payload: dict[str, Any]) -> None:
        self._outgoing.append(payload)
        self._log_message(f"queued {payload['type']} payload")

    def _enqueue_ack(self, payload: dict[str, Any]) -> None:
        if not self._connected:
            self._log_message("ignored ack because dummy server is stopped")
            return

        ack = {
            "ts": time.time(),
            "role": self._role,
            "status": "stubbed",
            "payload": payload,
        }
        self._incoming.put(ack)

    def _log_message(self, msg: str) -> None:
        if self._log is not None:
            self._log(msg)
