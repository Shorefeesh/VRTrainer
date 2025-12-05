from __future__ import annotations

from typing import Any, Callable, MutableMapping, Optional, List
import time
from collections import deque
import uuid
import logging
import threading
import json
import queue

try:
    import requests
except ImportError:  # pragma: no cover - optional runtime dep when remote server is used
    requests = None  # type: ignore[assignment]

try:
    import websocket  # websocket-client
except ImportError:  # pragma: no cover
    websocket = None  # type: ignore[assignment]


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
        if websocket is None:  # pragma: no cover - import guard
            raise RuntimeError("websocket-client is required (pip install websocket-client)")

        self.base_url = base_url.rstrip("/")
        self._role = "trainer" if role == "trainer" else "pet"
        self._username = username.strip() or "Anonymous"
        self._log = log or logging.getLogger(__name__).debug
        self._timeout = timeout

        self._client_uuid = uuid.uuid4()
        self._connected = False
        self._session_id: str | None = None
        self._session_state: str = "idle"
        self._latest_settings: dict[str, Any] = {}
        self._session_users: list[dict[str, Any]] = []
        self._events: list[str] = []
        self._last_event_id: str | None = None
        self._last_session_refresh: float = 0.0
        # Track processed server event ids to avoid duplicate log spam when polling
        # and when periodically refreshing session details.
        self._seen_event_ids: deque[str] = deque(maxlen=200)
        self._seen_event_ids_set: set[str] = set()
        self._stats_by_user: dict[str, list[dict[str, Any]]] = {}
        self._ws: websocket.WebSocketApp | None = None
        self._ws_thread: threading.Thread | None = None
        self._ws_stop = threading.Event()
        self._incoming: "queue.Queue[dict[str, Any]]" = queue.Queue()

    # Internal connection state helpers ----------------------------
    def _mark_disconnected(self, reason: str | None = None) -> None:
        if self._connected is False:
            return
        self._connected = False
        if reason:
            self._record_event_string(f"disconnected: {reason}")
        else:
            self._record_event_string("disconnected from server")

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
            self._mark_disconnected(str(exc))

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
        self._ws_stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._ws_thread = None

    def record_local_event(self, message: str) -> None:
        """Append a log line to the session event list without server IO."""

        self._record_event_string(message)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # Trainer → server -----------------------------------------------
    def send_config(self, settings: MutableMapping[str, Any], target_client: str | None = None) -> None:
        """Send trainer profile/config updates to a specific pet client."""

        # Allow convenience of passing an iterable of client ids.
        if isinstance(target_client, (list, tuple, set)):
            for client in target_client:
                self.send_config(settings, target_client=str(client))
            return

        if not target_client:
            self._log("skip config send: no target_client")
            return

        self._latest_settings = dict(settings)
        self._send_ws(
            {
                "type": "config",
                "from_client": str(self._client_uuid),
                "target_scope": "per_client",
                "target_client": str(target_client),
                "payload": dict(settings),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    def send_command(self, phrase: str, metadata: MutableMapping[str, Any] | None = None) -> None:
        """Send any trainer-issued instruction (tricks, scold, focus, proximity, etc.)."""
        meta = dict(metadata or {})
        payload = {"phrase": phrase, "meta": meta, "type": "command"}
        self._send_ws(
            {
                "type": "command",
                "from_client": str(self._client_uuid),
                "target_scope": "per_client" if meta.get("target_client") else "broadcast",
                "target_client": meta.get("target_client"),
                "payload": payload,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    def send_logs(self, stats: MutableMapping[str, Any]) -> None:
        """Pet-emitted metrics/telemetry."""
        self._send_ws(
            {
                "type": "logs",
                "from_client": str(self._client_uuid),
                "target_scope": "per_client" if stats.get("target_client") else "broadcast",
                "target_client": stats.get("target_client"),
                "payload": dict(stats),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    def send_status(self, status: MutableMapping[str, Any]) -> None:
        """Status from OSC/whisper/pishock."""
        self._send_ws(
            {
                "type": "status",
                "from_client": str(self._client_uuid),
                "target_scope": "broadcast",
                "target_client": None,
                "payload": dict(status),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    # Session management ---------------------------------------------
    def start_session(self, session_label: str | None = None) -> dict[str, Any]:
        session_id = (session_label or f"s-{uuid.uuid4().hex[:6]}").strip()
        payload = {"session_id": session_id, "client_uuid": str(self._client_uuid), "role": self._server_role}
        data = self._post("/sessions", payload)
        self._session_id = data.get("session_id")
        self._session_state = "hosting"
        self._record_event_string(f"started session {self._session_id}")
        self._connect_ws()
        try:
            self._refresh_session_users(force=True)
        except Exception:
            pass
        return self.get_session_details()

    def join_session(self, session_id: str) -> dict[str, Any]:
        cleaned = session_id.strip()
        if not cleaned:
            raise ValueError("Session code cannot be empty")

        payload = {"client_uuid": str(self._client_uuid), "role": self._server_role}
        data = self._post(f"/sessions/{cleaned}/join", payload)
        self._session_id = data.get("session_id", cleaned)
        self._session_state = "joined"
        participants = data.get("participants")
        if participants:
            self._session_users = list(participants)
            self._last_session_refresh = time.time()
        self._record_event_string(f"joined session {self._session_id}")
        self._connect_ws()
        return self.get_session_details()

    def leave_session(self) -> dict[str, Any]:
        if self._session_id:
            try:
                self._post(f"/sessions/{self._session_id}/leave", {"client_uuid": str(self._client_uuid)})
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
        # Opportunistically refresh roster data so the UI has pet identifiers.
        try:
            self._refresh_session_users()
        except Exception:
            pass

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

    @property
    def _server_role(self) -> str:
        """Map UI-facing role names to server-facing leader/follower."""
        return "leader" if self._role == "trainer" else "follower"

    # Server → client polling ----------------------------------------
    def poll_events(
        self, limit: int = 10, *, predicate: Callable[[dict[str, Any]], bool] | None = None
    ) -> list[dict[str, Any]]:
        if not self._session_id or not self._connected:
            return []

        matched: list[dict[str, Any]] = []
        drained: int = 0
        while drained < limit:
            try:
                evt = self._incoming.get_nowait()
            except queue.Empty:
                break
            drained += 1
            if predicate is None or predicate(evt):
                matched.append(evt)
        return matched

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._latest_settings.get(key, default)

    @property
    def latest_settings(self) -> dict[str, Any]:
        return dict(self._latest_settings)

    # Internal helpers -----------------------------------------------
    def _capture_session(self, session: dict[str, Any]) -> None:
        # Control-plane responses are minimal; keep any available metadata.
        self._session_id = session.get("session_id", self._session_id)

    def _record_event_string(self, message: str) -> None:
        if not message:
            return
        timestamp = time.strftime("%H:%M:%S")
        self._events.append(f"[{timestamp}] {message}")
        if len(self._events) > 50:
            self._events = self._events[-50:]

    def _record_event(self, evt: dict[str, Any]) -> None:
        """Format and store a server event, ignoring duplicates by id."""

        # WebSocket messages already filtered; keep a human-readable echo.
        message = self._format_event(evt)
        if message:
            self._record_event_string(message)

    def _format_event(self, evt: dict[str, Any]) -> str:
        evt_type = (evt.get("type") or "").lower()
        payload = evt.get("payload") or {}
        if evt_type == "status":
            return ""
        if evt_type == "logs":
            return ""

        phrase = payload.get("phrase")
        if evt_type == "command" and phrase:
            return f"{evt.get('from_client', '-')[:8]} command: {phrase}"
        if evt_type == "config":
            return "config updated"
        return evt_type or "event"

    def _refresh_session_users(self, *, force: bool = False) -> None:
        """Fetch the latest session participant roster from the server."""

        if not self._session_id or not self._connected:
            return

        now = time.time()
        if not force and now - self._last_session_refresh < 2.0:
            return

        try:
            data = self._get(f"/sessions/{self._session_id}")
        except Exception:
            return

        participants = data.get("participants")
        if isinstance(participants, list):
            self._session_users = list(participants)
            self._last_session_refresh = now

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        try:
            resp = requests.get(f"{self.base_url}{path}", params=params, timeout=self._timeout)
            resp.raise_for_status()
            self._connected = True
            return resp.json()
        except Exception as exc:
            self._mark_disconnected(str(exc))
            raise

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = requests.post(f"{self.base_url}{path}", json=payload, timeout=self._timeout)
            resp.raise_for_status()
            self._connected = True
            return resp.json()
        except Exception as exc:
            self._mark_disconnected(str(exc))
            raise

    # WebSocket helpers -------------------------------------------------
    def _connect_ws(self) -> None:
        if not self._session_id or self._ws_thread is not None:
            return

        ws_url = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/sessions/{self._session_id}/ws?client_uuid={self._client_uuid}"

        def _on_open(_ws: websocket.WebSocketApp) -> None:
            self._connected = True
            self._record_event_string("ws connected")

        def _on_close(_ws: websocket.WebSocketApp, _code: int, _msg: str) -> None:
            self._record_event_string("ws closed")
            self._connected = False

        def _on_error(_ws: websocket.WebSocketApp, err: Exception) -> None:
            self._log(f"ws error: {err}")

        def _on_message(_ws: websocket.WebSocketApp, msg: str) -> None:
            try:
                data = json.loads(msg)
                if data.get("type") == "config":
                    self._latest_settings = data.get("payload", {})
                self._incoming.put(data)
                self._record_event(data)
            except Exception:
                return

        self._ws_stop.clear()
        self._ws = websocket.WebSocketApp(
            ws_url,
            on_open=_on_open,
            on_close=_on_close,
            on_error=_on_error,
            on_message=_on_message,
        )

        def _run() -> None:
            while not self._ws_stop.is_set():
                try:
                    self._ws.run_forever(ping_interval=20, ping_timeout=5)
                except Exception as exc:
                    self._log(f"ws run error: {exc}")
                time.sleep(2)

        self._ws_thread = threading.Thread(target=_run, name="vrtrainer-ws", daemon=True)
        self._ws_thread.start()

    def _send_ws(self, message: dict[str, Any]) -> None:
        if not self._ws or not self._connected:
            return
        try:
            self._ws.send(json.dumps(message))
        except Exception as exc:
            self._log(f"ws send failed: {exc}")
