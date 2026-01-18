from __future__ import annotations

from typing import Callable, Iterable


class VRChatOSCInterface:
    """Interface to VRChat OSC parameters.

    Listens for OSC messages from VRChat on localhost:9001 and tracks
    simple diagnostics that can be surfaced in the UI, such as how many
    messages have been received recently and which avatar parameters
    have been observed.
    """

    def __init__(
        self,
        log_all_events: Callable[[str], None] | None = None,
        log_relevant_events: Callable[[str], None] | None = None,
        *,
        role: str = "pet",
    ) -> None:
        from collections import deque
        import threading

        self._running = False
        self._host = "127.0.0.1"
        self._port = 9001
        self._tx_port = 9000

        # Only the pet runtime should attach to VRChat OSC. The trainer
        # receives data through the server instead of binding a local
        # OSC port.
        self._role = "pet" if role == "pet" else "trainer"
        self._enabled = self._role == "pet"

        self._lock = threading.Lock()
        self._message_times = deque()
        self._trainer_params_seen: set[str] = set()
        self._expected_trainer_params:  set[str] = {
            "Trainer/Menu/Shock",
            "Trainer/Menu/Vibrate",
        }
        self._expected_pet_params: set[str] = {
            "Trainer/Proximity",
            "Trainer/ProximityHead",
            "Trainer/EyeLeft",
            "Trainer/EyeFarLeft",
            "Trainer/EyeRight",
            "Trainer/EyeFarRight",
            "Trainer/Paw",
            "Trainer/HipsFloorMin",
            "Trainer/HipsFloorMax",
            "Trainer/HeadFloorMin",
            "Trainer/HeadFloorMax",
            "Trainer/HandFloorLeftMin",
            "Trainer/HandFloorLeftMax",
            "Trainer/HandFloorRightMin",
            "Trainer/HandFloorRightMax",
            "Trainer/FootFloorLeftMin",
            "Trainer/FootFloorLeftMax",
            "Trainer/FootFloorRightMin",
            "Trainer/FootFloorRightMax",
            "Trainer/PenDepth",
            "LeftEar_IsGrabbed",
            "LeftEar_Stretch",
            "RightEar_IsGrabbed",
            "RightEar_Stretch",
            "Tail_IsGrabbed",
            "Tail_Stretch",
            "OGB/Orf/Pussy/PenOthers",
            "OGB/Orf/Ass/PenOthers",
            "OGB/Orf/Mouth/PenOthers",
        }
        self._param_values: dict[str, object] = {}

        self._log_relevant_events = log_relevant_events

        self._tx_client = None

        self._server = None
        self._thread = None

    def start(self) -> None:
        """Start OSC handling and begin listening on localhost:9001."""
        if self._running:
            return

        if not self._enabled:
            # Trainer side: skip binding the OSC server entirely.
            self._running = False
            self._log_message(self._log_relevant_events, "OSC listener disabled on trainer runtime")
            return

        try:
            from pythonosc.dispatcher import Dispatcher
            from pythonosc.osc_server import ThreadingOSCUDPServer
        except Exception:
            self._running = False
            return

        import threading

        dispatcher = Dispatcher()
        dispatcher.map("/*", self._on_osc_message)
        dispatcher.set_default_handler(self._on_osc_message)

        try:
            server = ThreadingOSCUDPServer((self._host, self._port), dispatcher)
        except OSError:
            self._running = False
            return

        self._server = server
        self._running = True

        thread = threading.Thread(target=server.serve_forever, name="VRChatOSC", daemon=True)
        self._thread = thread
        thread.start()

        self._log_message(self._log_relevant_events, "OSC listener started on {self._host}:{self._port}")

    def stop(self) -> None:
        """Stop OSC handling."""
        self._running = False
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        self._thread = None

    # Outbound helpers ------------------------------------------------
    def _ensure_tx_client(self):
        """Create (or return) the UDP client used to send OSC to VRChat."""

        if self._tx_client is not None:
            return self._tx_client

        try:
            from pythonosc.udp_client import SimpleUDPClient

            self._tx_client = SimpleUDPClient(self._host, self._tx_port)
        except Exception:
            self._tx_client = None

        return self._tx_client

    def send_parameter(self, name: str, value: object) -> bool:
        """Send a single avatar parameter to the local VRChat client.

        Returns ``True`` when the message was queued successfully.
        This works even when OSC listening is disabled on the trainer side.
        """

        client = self._ensure_tx_client()
        if client is None:
            return False

        address = f"/avatar/parameters/{name}"

        try:
            client.send_message(address, value)
            self._log_message(self._log_relevant_events, f"OSC send {address} value={value}")
            return True
        except Exception:
            return False

    def pulse_parameter(
        self,
        name: str,
        *,
        value_on: object = 1,
        value_off: object = 0,
        duration: float = 0.2,
    ) -> None:
        """Toggle an avatar parameter on briefly, then turn it off.

        A short pulse works well for trigger-style bool parameters on
        the avatar. Failures are swallowed to keep the trainer loop
        resilient.
        """

        if not self.send_parameter(name, value_on):
            return

        if duration <= 0:
            return

        import threading
        import time

        def _reset() -> None:
            time.sleep(duration)
            self.send_parameter(name, value_off)

        threading.Thread(target=_reset, name=f"OSCPulse:{name}", daemon=True).start()

    # Internal helpers -------------------------------------------------
    def _on_osc_message(self, address: str, *values: object) -> None:
        """Default handler for all incoming OSC messages."""
        import time

        now = time.time()
        cutoff = now - 10.0

        param_name: str | None = None
        is_relevant_param = False

        with self._lock:
            self._message_times.append(now)
            while self._message_times and self._message_times[0] < cutoff:
                self._message_times.popleft()

            prefix_all = "/avatar/parameters/"
            if address.startswith(prefix_all):
                param_name = address[len(prefix_all) :]
                value = values[0] if values else None
                self._param_values[param_name] = value
                is_relevant_param = self._is_relevant_param(param_name)

            prefix = "/avatar/parameters/Trainer/"
            if address.startswith(prefix):
                trainer_suffix = address[len("/avatar/parameters/") :]
                self._trainer_params_seen.add(trainer_suffix)

        self._log_osc_message(address, values, is_relevant_param)

    # Public diagnostics -----------------------------------------------
    def get_status_snapshot(self) -> dict:
        """Return a snapshot of recent OSC message and parameter status."""
        import time

        now = time.time()
        cutoff = now - 10.0

        with self._lock:
            while self._message_times and self._message_times[0] < cutoff:
                self._message_times.popleft()
            messages_last_10s = len(self._message_times)

            expected_trainer = set(self._expected_trainer_params)
            seen_trainer = set(self._trainer_params_seen)

            expected_pet = set(self._expected_pet_params)
            seen_pet = {name for name in self._param_values.keys() if name in expected_pet}

        found_trainer = len(expected_trainer & seen_trainer)
        missing_trainer = sorted(expected_trainer - seen_trainer)

        found_pet = len(seen_pet)
        missing_pet = sorted(expected_pet - seen_pet)

        return {
            "enabled": self._enabled,
            "messages_last_10s": messages_last_10s,
            "expected_trainer_params_total": len(expected_trainer),
            "found_trainer_params": found_trainer,
            "missing_trainer_params": missing_trainer,
            "expected_pet_params_total": len(expected_pet),
            "found_pet_params": found_pet,
            "missing_pet_params": missing_pet,
        }

    @property
    def is_running(self) -> bool:
        return self._enabled and self._running

    # Parameter access -------------------------------------------------
    def get_parameter(self, name: str, default: object | None = None) -> object | None:
        """Return the most recent value for the given avatar parameter.

        The ``name`` should be the suffix after ``/avatar/parameters/``,
        for example ``\"LeftEar_IsGrabbed\"`` or ``\"Tail_Stretch\"``.
        """
        with self._lock:
            return self._param_values.get(name, default)

    def get_bool_param(self, name: str, default: object | None = None) -> bool:
        """Interpret an OSC parameter as a boolean."""
        raw = self.get_parameter(name, default)
        if raw is None:
            return False

        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw != 0
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return bool(raw)

    def get_float_param(self, name: str, default: object | None = None) -> float:
        """Interpret an OSC parameter as a float in the 0–1 range."""
        raw = self.get_parameter(name, default)
        if raw is None:
            return 0.0

        if isinstance(raw, bool):
            value = 1.0 if raw else 0.0
        elif isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str):
            try:
                value = float(raw.strip())
            except ValueError:
                return 0.0
        else:
            return 0.0

        # Clamp to [0, 1] as documented for stretch parameters.
        return max(0.0, min(1.0, value))

    def _is_relevant_param(self, param_name: str) -> bool:
        return param_name in self._expected_trainer_params or param_name in self._expected_pet_params

    def _format_osc_line(self, address: str, values: Iterable[object]) -> str:
        if not values:
            return address
        value_repr = ", ".join(repr(value) for value in values)
        return f"{address} -> {value_repr}"

    def _log_message(self, logger: Callable[[str], None] | None, message: str) -> None:
        try:
            if logger is not None:
                logger(message)
        except Exception:
            return

    def _log_osc_message(self, address: str, values: Iterable[object], is_relevant: bool) -> None:
        if is_relevant:
            line = self._format_osc_line(address, values)
            self._log_message(self._log_relevant_events, line)
