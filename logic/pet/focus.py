from __future__ import annotations

from typing import Optional

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import RemoteServerInterface
from logic.logging_utils import LogFile


class FocusFeature:
    """Pet focus feature.

    Runs on the pet client, reading OSC eye-contact parameters and
    delivering shocks locally when focus drops too low.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        server: RemoteServerInterface | None = None,
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

        # Focus meter state and tunables.
        self._focus_meter: float = 1.0
        self._poll_interval: float = 0.1
        self._fill_rate: float = 0.2
        self._drain_rate: float = 0.02
        self._shock_threshold: float = 0.2

        self._base_cooldown_seconds: float = 5.0
        self._cooldown_seconds: float = self._base_cooldown_seconds
        self._cooldown_until: float = 0.0

        self._base_shock_strength_min: float = 20.0
        self._base_shock_strength_max: float = 80.0
        self._shock_strength_min: float = self._base_shock_strength_min
        self._shock_strength_max: float = self._base_shock_strength_max
        self._base_shock_duration: float = 0.5
        self._shock_duration: float = self._base_shock_duration

        self._last_tick: float | None = None
        self._last_sample_log: float = 0.0

        self._name_penalty: float = 0.15

        self.set_scaling(
            delay_scale=1.0,
            cooldown_scale=(scaling or {}).get("cooldown_scale", 1.0),
            duration_scale=(scaling or {}).get("duration_scale", 1.0),
            strength_scale=(scaling or {}).get("strength_scale", 1.0),
        )

        self._log("event=init feature=focus runtime=pet")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        import threading

        thread = self._thread = threading.Thread(
            target=self._worker_loop,
            name="PetFocusFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=focus runtime=pet")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=focus runtime=pet")

    # Internal helpers -------------------------------------------------
    def set_scaling(
        self,
        *,
        delay_scale: float = 1.0,
        cooldown_scale: float = 1.0,
        duration_scale: float = 1.0,
        strength_scale: float = 1.0,
    ) -> None:
        self._cooldown_seconds = max(0.0, self._base_cooldown_seconds * cooldown_scale)
        self._shock_duration = max(0.0, self._base_shock_duration * duration_scale)
        self._shock_strength_min = max(0.0, self._base_shock_strength_min * strength_scale)
        self._shock_strength_max = max(self._shock_strength_min, self._base_shock_strength_max * strength_scale)

    def _worker_loop(self) -> None:
        import time

        self._last_tick = time.time()

        while not self._stop_event.is_set():
            now = time.time()
            dt = max(0.0, now - (self._last_tick or now))
            self._last_tick = now

            if not self._enabled:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            self._apply_remote_penalties()
            self._update_meter(dt)
            self._log_sample(now)

            if self._should_shock(now):
                self._deliver_correction()
                self._cooldown_until = now + self._cooldown_seconds

            if self._stop_event.wait(self._poll_interval):
                break

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def _update_meter(self, dt: float) -> None:
        focused = self.osc.get_bool_param("Trainer/Focus", default=False)
        delta = (self._fill_rate if focused else -self._drain_rate) * dt
        self._focus_meter = max(0.0, min(1.0, self._focus_meter + delta))

    def _apply_remote_penalties(self) -> None:
        """Apply penalties based on trainer-issued focus commands."""

        if self.server is None:
            return

        events = self.server.poll_events(
            limit=5,
            predicate=lambda evt: (
                isinstance(evt, dict)
                and isinstance(evt.get("payload"), dict)
                and evt.get("payload", {}).get("type") == "command"
                and evt.get("payload", {}).get("meta", {}).get("feature") == "focus"
            ),
        )

        if not events:
            return

        for _ in events:
            self._focus_meter = max(0.0, self._focus_meter - self._name_penalty)

    def _should_shock(self, now: float) -> bool:
        if now < self._cooldown_until:
            return False
        return self._focus_meter <= self._shock_threshold

    def _deliver_correction(self) -> None:
        try:
            deficit = (self._shock_threshold - self._focus_meter) / self._shock_threshold
            strength = max(self._shock_strength_min, min(self._shock_strength_max, int(deficit * self._shock_strength_max)))
            self.pishock.send_shock(strength=strength, duration=self._shock_duration)
            self._log(
                f"event=shock feature=focus runtime=pet meter={self._focus_meter:.3f} threshold={self._shock_threshold:.3f} strength={strength}"
            )
            self._send_stats(
                {
                    "event": "shock",
                    "runtime": "pet",
                    "feature": "focus",
                    "meter": self._focus_meter,
                    "threshold": self._shock_threshold,
                    "strength": strength,
                }
            )
        except Exception:
            return

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return

    def _log_sample(self, now: float) -> None:
        if now - self._last_sample_log < 1.0:
            return

        self._last_sample_log = now
        self._log(
            f"event=sample feature=focus runtime=pet meter={self._focus_meter:.3f} threshold={self._shock_threshold:.3f}"
        )
        self._send_stats(
            {
                "event": "sample",
                "runtime": "pet",
                "feature": "focus",
                "meter": self._focus_meter,
                "threshold": self._shock_threshold,
            }
        )

    @staticmethod
    def _normalise(text: str) -> str:
        if not text:
            return ""

        chars: list[str] = []
        for ch in text.lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch.isspace():
                chars.append(" ")
            else:
                chars.append(" ")

        return " ".join("".join(chars).split())

    def _send_stats(self, stats: dict[str, object]) -> None:
        server = self.server
        if server is None:
            return

        try:
            server.send_logs(stats)
        except Exception:
            return
