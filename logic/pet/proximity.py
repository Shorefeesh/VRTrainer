from __future__ import annotations

from typing import Optional

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import DummyServerInterface
from logic.logging_utils import LogFile


class ProximityFeature:
    """Pet proximity feature.

    Runs on the pet to monitor distance from the trainer via OSC and
    issue local shocks when too far away or when summon commands are
    ignored.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        server: DummyServerInterface | None = None,
        *,
        scaling: Optional[dict[str, float]] = None,
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

        # Tunables.
        self._poll_interval: float = 0.1
        self._proximity_threshold: float = 0.4
        self._base_breach_duration: float = 0.5
        self._breach_duration: float = self._base_breach_duration
        self._base_cooldown_seconds: float = 5.0
        self._cooldown_seconds: float = self._base_cooldown_seconds
        self._cooldown_until: float = 0.0
        self._breach_started_at: float | None = None
        self._base_shock_strength_min: float = 20.0
        self._base_shock_strength_max: float = 80.0
        self._shock_strength_min: float = self._base_shock_strength_min
        self._shock_strength_max: float = self._base_shock_strength_max
        self._base_shock_duration: float = 0.5
        self._shock_duration: float = self._base_shock_duration
        self.set_scaling(
            delay_scale=(scaling or {}).get("delay_scale", 1.0),
            cooldown_scale=(scaling or {}).get("cooldown_scale", 1.0),
            duration_scale=(scaling or {}).get("duration_scale", 1.0),
            strength_scale=(scaling or {}).get("strength_scale", 1.0),
        )

        # Summon command tracking triggered via the trainer/server path.
        self._base_command_timeout: float = 4.0
        self._command_timeout: float = self._base_command_timeout
        self._command_target: float = 1
        self._pending_command_deadline: float | None = None
        self._last_sample_log: float = 0.0

        self._log("event=init feature=proximity runtime=pet")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        import threading

        thread = self._thread = threading.Thread(
            target=self._worker_loop,
            name="PetProximityFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=proximity runtime=pet")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=proximity runtime=pet")

    # Internal helpers -------------------------------------------------
    def set_scaling(
        self,
        *,
        delay_scale: float = 1.0,
        cooldown_scale: float = 1.0,
        duration_scale: float = 1.0,
        strength_scale: float = 1.0,
    ) -> None:
        self._breach_duration = max(0.0, self._base_breach_duration * delay_scale)
        self._command_timeout = max(0.0, self._base_command_timeout * delay_scale)
        self._cooldown_seconds = max(0.0, self._base_cooldown_seconds * cooldown_scale)
        self._shock_duration = max(0.0, self._base_shock_duration * duration_scale)
        self._shock_strength_min = max(0.0, self._base_shock_strength_min * strength_scale)
        self._shock_strength_max = max(self._shock_strength_min, self._base_shock_strength_max * strength_scale)

    def _worker_loop(self) -> None:
        import time

        while not self._stop_event.is_set():
            now = time.time()
            proximity_value = self.osc.get_float_param("Trainer/Proximity", default=1.0)

            if not self._enabled:
                self._breach_started_at = None
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            if self._detect_remote_summon():
                self._pending_command_deadline = now + self._command_timeout
                self._log("event=command_start feature=proximity runtime=pet name=summon")

            if self._pending_command_deadline is not None:
                if self._meets_command_target(proximity_value):
                    self._pending_command_deadline = None
                    self._log(
                        f"event=command_success feature=proximity runtime=pet name=summon proximity={proximity_value:.3f}"
                    )
                elif now >= self._pending_command_deadline and now >= self._cooldown_until:
                    self._deliver_correction("summon command missed", proximity_value)
                    self._cooldown_until = now + self._cooldown_seconds
                    self._pending_command_deadline = None

            if now >= self._cooldown_until and self._is_too_far(now, proximity_value):
                self._deliver_correction("too far from trainer", proximity_value)
                self._cooldown_until = now + self._cooldown_seconds
                self._breach_started_at = None

            self._log_sample(now, proximity_value)

            if self._stop_event.wait(self._poll_interval):
                break

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self._breach_started_at = None

    def _is_too_far(self, now: float, proximity_value: float) -> bool:
        value = proximity_value

        if value >= self._proximity_threshold:
            self._breach_started_at = None
            return False

        if self._breach_started_at is None:
            self._breach_started_at = now
            return False

        return (now - self._breach_started_at) >= self._breach_duration

    def _deliver_correction(self, reason: str, proximity_value: float | None = None) -> None:
        try:
            proximity = (
                proximity_value if proximity_value is not None else self.osc.get_float_param("Trainer/Proximity", default=0.0)
            )
            distance_factor = max(0.0, (self._proximity_threshold - proximity) / self._proximity_threshold)
            strength = max(self._shock_strength_min, min(self._shock_strength_max, int(distance_factor * self._shock_strength_max)))
            self.pishock.send_shock(strength=strength, duration=self._shock_duration)
            self._log(
                f"event=shock feature=proximity runtime=pet reason={reason.replace(' ', '_')} proximity={proximity:.3f} threshold={self._proximity_threshold:.3f} strength={strength}"
            )
        except Exception:
            return

    def _detect_remote_summon(self) -> bool:
        if self.server is None:
            return False

        events = self.server.poll_events(
            limit=5,
            predicate=lambda evt: (
                isinstance(evt, dict)
                and isinstance(evt.get("payload"), dict)
                and evt.get("payload", {}).get("type") == "command"
                and evt.get("payload", {}).get("meta", {}).get("feature") == "proximity"
            ),
        )

        return bool(events)

    def _meets_command_target(self, proximity_value: float | None = None) -> bool:
        proximity = (
            proximity_value if proximity_value is not None else self.osc.get_float_param("Trainer/Proximity", default=0.0)
        )
        return proximity >= self._command_target

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return

    def _log_sample(self, now: float, proximity_value: float) -> None:
        if now - self._last_sample_log < 1.0:
            return

        self._last_sample_log = now
        self._log(
            f"event=sample feature=proximity runtime=pet value={proximity_value:.3f} threshold={self._proximity_threshold:.3f}"
        )

