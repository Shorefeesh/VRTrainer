from __future__ import annotations

from typing import Any, Callable, MutableMapping
import time
from collections import deque
import uuid


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
        self._session_id: str | None = None
        self._session_state: str = "idle"
        self._session_events: list[str] = []

        self._outgoing: list[dict[str, Any]] = []
        self._incoming: deque[dict[str, Any]] = deque()
        self._latest_settings: dict[str, Any] = {}

        self._username: str = "Anonymous"
        self._session_users: list[dict[str, str]] = []

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

    # Session management stubs ---------------------------------------
    def start_session(self, session_label: str | None = None) -> dict[str, Any]:
        """Simulate hosting a new session and return details."""
        self._session_id = session_label or f"session-{uuid.uuid4().hex[:8]}"
        self._session_state = "hosting"
        self._session_users = []
        self._add_or_update_user(self._username, self._role)
        self._ensure_pending_placeholder()
        self._record_session_event(f"started session {self._session_id}")
        return self.get_session_details()

    def join_session(self, session_id: str) -> dict[str, Any]:
        """Simulate joining an existing session and return details."""
        cleaned = session_id.strip()
        if not cleaned:
            raise ValueError("Session code cannot be empty")

        self._session_id = cleaned
        self._session_state = "joined"
        if not self._session_users:
            self._session_users = [
                {"username": "Host", "status": "trainer"},
                {"username": "Guest", "status": "pending"},
            ]

        replaced_pending = self._replace_pending_with_self()
        if not replaced_pending:
            self._add_or_update_user(self._username, self._role)
        self._ensure_pending_placeholder()
        self._record_session_event(f"joined session {self._session_id}")
        return self.get_session_details()

    def leave_session(self) -> dict[str, Any]:
        """Simulate leaving the current session and return details."""
        if self._session_id:
            self._record_session_event(f"left session {self._session_id}")
        self._session_id = None
        self._session_state = "idle"
        self._session_users = []
        return self.get_session_details()

    def get_session_details(self) -> dict[str, Any]:
        """Return a snapshot of current session info and history."""
        return {
            "connected": self._connected,
            "role": self._role,
            "username": self._username,
            "session_id": self._session_id,
            "state": self._session_state,
            "latest_settings": dict(self._latest_settings),
            "events": list(self._session_events[-10:]),
            "session_users": [dict(user) for user in self._session_users],
        }

    def set_username(self, username: str) -> None:
        """Set the local username used when joining sessions."""
        cleaned = username.strip()
        old_username = self._username
        self._username = cleaned or "Anonymous"
        self._rename_user(old_username, self._username)

    # Server → trainer polling ---------------------------------------
    def poll_events(
        self, limit: int = 10, *, predicate: Callable[[dict[str, Any]], bool] | None = None
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` queued acknowledgements.

        When ``predicate`` is provided, only events that satisfy it are
        returned; unmatched events are preserved for other consumers.
        """

        matched: list[dict[str, Any]] = []
        unmatched: list[dict[str, Any]] = []

        while self._incoming and len(matched) < limit:
            item = self._incoming.popleft()
            if predicate is None or predicate(item):
                matched.append(item)
            else:
                unmatched.append(item)

        if unmatched:
            for item in reversed(unmatched):
                self._incoming.appendleft(item)

        return matched

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
        self._incoming.append(ack)

    def _log_message(self, msg: str) -> None:
        if self._log is not None:
            self._log(msg)

    def _record_session_event(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self._session_events.append(f"[{timestamp}] {message}")
        self._log_message(message)

    def _add_or_update_user(self, username: str, status: str) -> None:
        for user in self._session_users:
            if user.get("username") == username:
                user["status"] = status
                return
        self._session_users.append({"username": username, "status": status})

    def _ensure_pending_placeholder(self) -> None:
        if not any(user.get("status") == "pending" for user in self._session_users):
            self._session_users.append({"username": "Pending user", "status": "pending"})

    def _replace_pending_with_self(self) -> bool:
        for user in self._session_users:
            if user.get("status") == "pending":
                user["username"] = self._username
                user["status"] = self._role
                return True
        return False

    def _rename_user(self, old_username: str, new_username: str) -> None:
        for user in self._session_users:
            if user.get("username") == old_username:
                user["username"] = new_username
                return
