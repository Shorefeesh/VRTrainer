from __future__ import annotations

from typing import Any, Callable, MutableMapping, Optional
import time
from collections import deque
import uuid
import logging

try:
    import requests
except ImportError:  # pragma: no cover - optional runtime dep when remote server is used
    requests = None  # type: ignore[assignment]



class RemoteServerInterface:
    """HTTP client for the hosted vrtrainer.online API.

    Set the environment variable
    ``VRTRAINER_SERVER_URL`` (default ``https://vrtrainer.online``) to
    enable this interface.
    """

    def __init__(
        self,
        base_url: str = "https://vrtrainer.online",
        *,
        role: str = "trainer",
        username: str = "Anonymous",
        log: Callable[[str], None] | None = None,
        timeout: float = 6.0,
    ) -> None:
        if requests is None:  # pragma: no cover - import guard
            raise RuntimeError("requests is required for RemoteServerInterface (pip install requests)")

        self.base_url = base_url.rstrip("/")
        self._role = "trainer" if role == "trainer" else "pet"
        self._username = username.strip() or "Anonymous"
        self._log = log or logging.getLogger(__name__).debug
        self._timeout = timeout

        self._connected = False
        self._session_id: str | None = None
        self._session_state: str = "idle"
        self._latest_settings: dict[str, Any] = {}
        self._session_users: list[dict[str, Any]] = []
        self._events: list[str] = []
        self._last_event_id: str | None = None
        # Track processed server event ids to avoid duplicate log spam when polling
        # and when periodically refreshing session details.
        self._seen_event_ids: deque[str] = deque(maxlen=200)
        self._seen_event_ids_set: set[str] = set()
        self._stats_by_user: dict[str, list[dict[str, Any]]] = {}

    # Lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Mark as connected; performs a lightweight health probe."""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=self._timeout)
            resp.raise_for_status()
            self._log("remote server reachable")
            self._connected = True
        except Exception as exc:
            self._log(f"remote server health check failed: {exc}")
            self._connected = False

    def stop(self) -> None:
        self._connected = False
        self._session_id = None
        self._session_state = "idle"
        self._session_users = []
        self._events = []
        self._last_event_id = None
        self._seen_event_ids.clear()
        self._seen_event_ids_set.clear()
        self._stats_by_user = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    # Trainer → server -----------------------------------------------
    def send_settings(self, settings: MutableMapping[str, Any]) -> None:
        if not self._session_id:
            return
        self._post(
            f"/api/sessions/{self._session_id}/settings",
            {"username": self._username, "role": self._role, "settings": dict(settings)},
        )

    def send_command(self, phrase: str, metadata: MutableMapping[str, Any] | None = None) -> None:
        if not self._session_id:
            return
        self._post(
            f"/api/sessions/{self._session_id}/command",
            {"username": self._username, "role": self._role, "phrase": phrase, "meta": dict(metadata or {})},
        )

    def send_scold(self, phrase: str, metadata: MutableMapping[str, Any] | None = None) -> None:
        if not self._session_id:
            return
        self._post(
            f"/api/sessions/{self._session_id}/scold",
            {"username": self._username, "role": self._role, "phrase": phrase, "meta": dict(metadata or {})},
        )

    def send_stats(self, stats: MutableMapping[str, Any]) -> None:
        if not self._session_id:
            return
        self._post(
            f"/api/sessions/{self._session_id}/stats",
            {"username": self._username, "role": self._role, "stats": dict(stats)},
        )

    # Session management ---------------------------------------------
    def start_session(self, session_label: str | None = None) -> dict[str, Any]:
        payload = {"username": self._username, "role": self._role, "session_label": session_label}
        data = self._post("/api/sessions", payload)
        session = data.get("session", {})
        self._capture_session(session)
        self._session_state = "hosting"
        self._record_event_string(f"started session {self._session_id}")
        return self.get_session_details()

    def join_session(self, session_id: str) -> dict[str, Any]:
        cleaned = session_id.strip()
        if not cleaned:
            raise ValueError("Session code cannot be empty")

        payload = {"username": self._username, "role": self._role}
        data = self._post(f"/api/sessions/{cleaned}/join", payload)
        session = data.get("session", {})
        self._capture_session(session)
        self._session_state = "joined"
        self._record_event_string(f"joined session {self._session_id}")
        return self.get_session_details()

    def leave_session(self) -> dict[str, Any]:
        if self._session_id:
            try:
                self._post(f"/api/sessions/{self._session_id}/leave", {"username": self._username, "role": self._role})
            except Exception:
                pass
            self._record_event_string(f"left session {self._session_id}")
        self._session_id = None
        self._session_state = "idle"
        self._session_users = []
        self._events = []
        self._last_event_id = None
        return self.get_session_details()

    def get_session_details(self) -> dict[str, Any]:
        if self._session_id and self._connected:
            try:
                session_resp = self._get(f"/api/sessions/{self._session_id}")
                session = session_resp.get("session", {})
                self._capture_session(session)
            except Exception as exc:
                self._log(f"session refresh failed: {exc}")

        return {
            "connected": self._connected,
            "role": self._role,
            "username": self._username,
            "session_id": self._session_id,
            "state": self._session_state,
            "latest_settings": dict(self._latest_settings),
            "events": list(self._events[-10:]),
            "session_users": [dict(u) for u in self._session_users],
            "stats_by_user": {k: list(v) for k, v in self._stats_by_user.items()},
        }

    def set_username(self, username: str) -> None:
        cleaned = username.strip()
        self._username = cleaned or "Anonymous"

    def set_role(self, role: str) -> None:
        self._role = "trainer" if role == "trainer" else "pet"

    # Server → client polling ----------------------------------------
    def poll_events(
        self, limit: int = 10, *, predicate: Callable[[dict[str, Any]], bool] | None = None
    ) -> list[dict[str, Any]]:
        if not self._session_id or not self._connected:
            return []

        events: list[dict[str, Any]] = []
        try:
            data = self._get(
                f"/api/sessions/{self._session_id}/events",
                params={"after": self._last_event_id, "limit": max(1, min(limit, 50))},
            )
            events = data.get("events", [])
        except Exception as exc:
            self._log(f"poll_events failed: {exc}")
            return []

        matched: list[dict[str, Any]] = []
        for evt in events:
            self._last_event_id = evt.get("id") or self._last_event_id
            payload = {"type": evt.get("type"), **(evt.get("payload") or {})}
            ack = {
                "ts": evt.get("ts", time.time()),
                "role": payload.get("role"),
                "status": "ok",
                "payload": payload,
            }
            if predicate is None or predicate(ack):
                matched.append(ack)

            self._record_event(evt)

        return matched

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._latest_settings.get(key, default)

    @property
    def latest_settings(self) -> dict[str, Any]:
        return dict(self._latest_settings)

    # Internal helpers -----------------------------------------------
    def _capture_session(self, session: dict[str, Any]) -> None:
        self._session_id = session.get("session_id")
        self._session_state = session.get("state") or self._session_state
        self._latest_settings = session.get("latest_settings") or {}
        users = session.get("users") or []
        self._session_users = [
            {"username": u.get("username"), "status": u.get("role"), "state": u.get("state", "connected")}
            for u in users
        ]
        self._stats_by_user = session.get("stats_by_user") or {}
        events = session.get("events") or []
        if events:
            self._last_event_id = events[-1].get("id", self._last_event_id)
            for evt in events:
                self._record_event(evt)

    def _record_event_string(self, message: str) -> None:
        if not message:
            return
        timestamp = time.strftime("%H:%M:%S")
        self._events.append(f"[{timestamp}] {message}")
        if len(self._events) > 50:
            self._events = self._events[-50:]

    def _record_event(self, evt: dict[str, Any]) -> None:
        """Format and store a server event, ignoring duplicates by id."""

        event_id = evt.get("id")
        if event_id and event_id in self._seen_event_ids_set:
            return

        message = self._format_event(evt)
        if not message:
            return

        if event_id:
            if len(self._seen_event_ids) == self._seen_event_ids.maxlen:
                oldest = self._seen_event_ids.popleft()
                self._seen_event_ids_set.discard(oldest)
            self._seen_event_ids.append(event_id)
            self._seen_event_ids_set.add(event_id)

        self._record_event_string(message)

    def _format_event(self, evt: dict[str, Any]) -> str:
        evt_type = evt.get("type") or "event"
        payload = evt.get("payload") or {}
        username = payload.get("username") or payload.get("user") or "-"
        phrase = payload.get("phrase")
        if evt_type in {"command", "scold"} and phrase:
            return f"{username} {evt_type}: {phrase}"
        if evt_type == "settings":
            return f"{username} updated settings"
        if evt_type == "session_created":
            return f"session created by {username}"
        if evt_type == "user_joined":
            return f"{username} joined"
        if evt_type == "user_left":
            return f"{username} left"
        return evt_type

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        resp = requests.get(f"{self.base_url}{path}", params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(f"{self.base_url}{path}", json=payload, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()
