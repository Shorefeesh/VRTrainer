from __future__ import annotations

from tkinter import ttk

from logic import services

from .shared import StatusIndicator


def format_osc_status(role: str, snapshot: dict | None) -> str:
    """Render a concise OSC status string."""

    if snapshot is None:
        return "No data"

    messages = snapshot.get("messages_last_10s", 0)

    if role == "trainer" :
        trainer_expected = snapshot.get("expected_trainer_params_total", 0) or 0
        trainer_found = snapshot.get("found_trainer_params", 0) or 0
        return f"msgs_last_10s={messages}; trainer_params={trainer_found}/{trainer_expected}"

    else:
        pet_expected = snapshot.get("expected_pet_params_total", 0) or 0
        pet_found = snapshot.get("found_pet_params", 0) or 0
        return f"msgs_last_10s={messages}; pet_params={pet_found}/{pet_expected}"


def format_pishock_status(status: dict | None, running: bool) -> str:
    """Summarise PiShock connectivity."""
    if not running:
        return "Stopped"
    if status is None:
        return "No data"
    if not status.get("enabled", True):
        return "Not used"
    if status.get("connected"):
        return "Connected"
    if status.get("has_credentials"):
        return "Not connected"
    return "Not configured"


def _osc_colour(running: bool, snapshot: dict | None) -> str:
    if not running:
        return "grey"
    if snapshot is None:
        return "orange"

    messages = snapshot.get("messages_last_10s", 0)
    pet_expected = snapshot.get("expected_pet_params_total", 0) or 0
    pet_found = snapshot.get("found_pet_params", 0) or 0
    missing = max(pet_expected - pet_found, 0)

    if messages == 0:
        return "red"
    if missing > 0:
        return "orange"
    return "green"


def _pishock_colour(text: str) -> str:
    lowered = text.lower()
    if lowered in {"connected"}:
        return "green"
    if lowered in {"not connected"}:
        return "orange"
    if lowered in {"not configured"}:
        return "red"
    return "grey"


def _whisper_colour(text: str, running: bool) -> str:
    if not running:
        return "grey"
    if not text or text.lower() == "stopped":
        return "red"
    return "green"


class ConnectionStatusPanel(ttk.LabelFrame):
    """Always-visible personal connection summary."""

    def __init__(self, master, *, refresh_ms: int = 1500) -> None:
        super().__init__(master, text="Connection status")
        self._refresh_ms = refresh_ms
        self._server_failure_seen = False

        self.server_indicator = StatusIndicator(self, "VRTrainer Server")
        self.osc_indicator = StatusIndicator(self, "VRChat OSC")
        self.pishock_indicator = StatusIndicator(self, "PiShock")
        self.whisper_indicator = StatusIndicator(self, "Whisper")

        for col, widget in enumerate(
            (
                self.server_indicator,
                self.osc_indicator,
                self.pishock_indicator,
                self.whisper_indicator,
            )
        ):
            widget.grid(row=0, column=col, sticky="w", padx=(0, 12))
            self.columnconfigure(col, weight=1)

        self._refresh()

    # Status helpers -------------------------------------------------
    def _update_server_indicator(self, connected: bool, events: list[str]) -> None:
        if connected:
            self._server_failure_seen = False
            self.server_indicator.set_status("Connected", "green")
            return

        lowered_events = " ".join(events).lower()
        has_failure = any(
            keyword in lowered_events for keyword in ("unreachable", "disconnected", "failed", "timeout")
        )
        if has_failure:
            self._server_failure_seen = True

        if self._server_failure_seen:
            self.server_indicator.set_status("Disconnected", "red")
        else:
            self.server_indicator.set_status("Idle", "grey")

    def _update_runtime_indicators(self, role: str | None) -> None:
        running = services.is_running()
        osc_status = services.get_osc_status() if running else None
        pishock_status = services.get_pishock_status() if running else None
        whisper_status = services.get_whisper_backend() if running else "Stopped"

        osc_text = format_osc_status(role or "", osc_status) if running else ("Stopped" if role else "Role not set")
        self.osc_indicator.set_status(osc_text, _osc_colour(running, osc_status))

        pishock_text = format_pishock_status(pishock_status, running)
        self.pishock_indicator.set_status(pishock_text, _pishock_colour(pishock_text))

        whisper_text = whisper_status or "Stopped"
        self.whisper_indicator.set_status(whisper_text, _whisper_colour(whisper_text, running))

    # Refresh loop ---------------------------------------------------
    def _refresh(self) -> None:
        try:
            details = services.get_server_session_details()
        except Exception:
            # Treat fetch errors as connection failures.
            self._server_failure_seen = True
            self.server_indicator.set_status("Disconnected", "red")
            self.osc_indicator.set_status("Role not set", "grey")
            self.pishock_indicator.set_status("Role not set", "grey")
            self.whisper_indicator.set_status("Role not set", "grey")
            self.after(self._refresh_ms, self._refresh)
            return

        connected = bool(details.get("connected"))
        events = details.get("events") or []
        role_raw = (details.get("role") or "").lower()
        role = role_raw if role_raw in {"trainer", "pet"} else None

        self._update_server_indicator(connected, events)
        self._update_runtime_indicators(role)

        self.after(self._refresh_ms, self._refresh)
