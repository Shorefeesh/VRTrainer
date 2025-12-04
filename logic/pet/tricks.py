from __future__ import annotations

import time

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import RemoteServerInterface
from logic.logging_utils import LogFile


class _PendingCommand:
    """Lightweight container for a command that is waiting to be completed."""

    def __init__(self, name: str, started_at: float, deadline: float) -> None:
        self.name = name
        self.started_at = started_at
        self.deadline = deadline


class TricksFeature:
    """Pet tricks feature.

    Runs on the pet client: detects trainer-issued voice commands via
    local Whisper and validates completion using OSC pose parameters.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        server: RemoteServerInterface | None = None,
        *,
        names: list[str] | None = None,
        scaling: dict[str, float] | None = None,
        logger: LogFile | None = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.server = server
        self._running = False
        self._enabled = True
        self._logger = logger

        import threading

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._pet_names = [self._normalise_text(name) for name in (names or []) if self._normalise_text(name)]

        self._poll_interval: float = 0.2
        self._base_command_timeout: float = 5.0
        self._command_timeout: float = self._base_command_timeout
        self._base_cooldown_seconds: float = 2.0
        self._cooldown_seconds: float = self._base_cooldown_seconds
        self._cooldown_until: float = 0.0
        self._base_shock_strength: float = 35
        self._shock_strength: float = self._base_shock_strength
        self._base_shock_duration: float = 0.5
        self._shock_duration: float = self._base_shock_duration
        self.set_scaling(
            delay_scale=(scaling or {}).get("delay_scale", 1.0),
            cooldown_scale=(scaling or {}).get("cooldown_scale", 1.0),
            duration_scale=(scaling or {}).get("duration_scale", 1.0),
            strength_scale=(scaling or {}).get("strength_scale", 1.0),
        )

        self._pending: _PendingCommand | None = None

        self._command_phrases: dict[str, list[str]] = {
            "paw": ["paw", "poor", "pour", "pore"],
            "sit": ["sit"],
            "lay_down": ["lay down", "laydown", "lie down", "layed down"],
            "beg": ["beg"],
            "play_dead": ["play dead", "playdead", "played dead"],
            "roll_over": ["rollover", "roll over"],
        }

        self._log("event=init feature=tricks runtime=pet")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        import threading

        thread = self._thread = threading.Thread(
            target=self._worker_loop,
            name="PetTricksFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=tricks runtime=pet")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=tricks runtime=pet")

    # Internal helpers -------------------------------------------------
    def set_scaling(
        self,
        *,
        delay_scale: float = 1.0,
        cooldown_scale: float = 1.0,
        duration_scale: float = 1.0,
        strength_scale: float = 1.0,
    ) -> None:
        self._command_timeout = max(0.0, self._base_command_timeout * delay_scale)
        self._cooldown_seconds = max(0.0, self._base_cooldown_seconds * cooldown_scale)
        self._shock_strength = max(0.0, self._base_shock_strength * strength_scale)
        self._shock_duration = max(0.0, self._base_shock_duration * duration_scale)

    def _worker_loop(self) -> None:
        import time

        while not self._stop_event.is_set():
            now = time.time()

            if not self._enabled:
                self._pending = None
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            self._maybe_start_command(now)

            if self._pending is not None:
                if self._is_command_completed(self._pending.name):
                    self._log(
                        f"event=command_success feature=tricks runtime=pet name={self._pending.name} duration={now - self._pending.started_at:.2f}"
                    )
                    self._deliver_completion_signal()
                    self._pending = None
                elif now >= self._pending.deadline and now >= self._cooldown_until:
                    self._deliver_failure()
                    self._cooldown_until = now + self._cooldown_seconds
                    self._pending = None

            if self._stop_event.wait(self._poll_interval):
                break

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self._pending = None

    def _maybe_start_command(self, now: float) -> None:
        """Start a new trick command if a trainer event was received."""

        if self.server is None:
            return

        events = self.server.poll_events(
            limit=5,
            predicate=lambda evt: (
                isinstance(evt, dict)
                and isinstance(evt.get("payload"), dict)
                and evt.get("payload", {}).get("type") == "command"
                and evt.get("payload", {}).get("meta", {}).get("feature") == "tricks"
            ),
        )

        for event in events:
            payload = event.get("payload", {})
            name = payload.get("phrase")
            if not name:
                continue

            normalised = self._normalise_text(str(name))
            if normalised not in self._command_phrases:
                continue

            self._pending = _PendingCommand(
                name=normalised,
                started_at=now,
                deadline=now + self._command_timeout,
            )
            self._log(f"event=command_start feature=tricks runtime=pet name={normalised}")
            self._deliver_task_start_signal()
            break

    def _is_command_completed(self, command: str) -> bool:
        if command == "paw":
            return self.osc.get_bool_param("Trainer/Paw", default=False)
        elif command == "sit":
            return self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "lay_down":
            return self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "beg":
            return not self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "play_dead":
            return not self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "roll_over":
            return not self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)

        return False

    def _deliver_failure(self) -> None:
        try:
            strength = int(self._shock_strength)
            self.pishock.send_shock(strength=strength, duration=self._shock_duration)
            self._log(
                f"event=shock feature=tricks runtime=pet name={self._pending.name if self._pending else 'unknown'} strength={strength}"
            )
        except Exception:
            return

    def _deliver_task_start_signal(self) -> None:
        try:
            self.pishock.send_shock(strength=1, duration=0.2)
            self._log("event=shock feature=tricks runtime=pet reason=task_start strength=1")
        except Exception:
            return

    def _deliver_completion_signal(self) -> None:
        try:
            for pulse in (1, 2):
                self.pishock.send_shock(strength=1, duration=0.2)
                self._log(f"event=shock feature=tricks runtime=pet reason=task_complete pulse={pulse} strength=1")
                if pulse == 1:
                    time.sleep(0.2)
        except Exception:
            return

    @staticmethod
    def _normalise_text(text: str) -> str:
        if not text:
            return ""

        chars: list[str] = []
        for ch in text.lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch == "_":
                chars.append("_")
            elif ch.isspace():
                chars.append(" ")
            else:
                chars.append(" ")

        return " ".join("".join(chars).split())

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return
