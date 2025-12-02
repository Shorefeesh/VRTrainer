from __future__ import annotations

from typing import Iterable, List, Optional

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface


class ProximityFeature:
    """Trainer proximity feature.

    Observes distance between trainer and pet via OSC, using PiShock to
    enforce staying close enough.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        whisper: WhisperInterface,
        difficulty: Optional[str] = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self._running = False

        # Background polling loop.
        import threading

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Tunables – could become user settings later.
        self._poll_interval: float = 0.1
        self._proximity_threshold: float = 0.4  # values below this are "too far"
        self._breach_duration: float = 0.5  # seconds the pet must be far before shocking
        self._cooldown_seconds: float = 5.0
        self._cooldown_until: float = 0.0
        self._breach_started_at: float | None = None
        self._shock_strength_min: float = 20.0
        self._shock_strength_max: float = 80.0
        self._apply_difficulty(difficulty)

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        thread = self._thread = self._thread_factory()
        thread.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

    # Internal helpers -------------------------------------------------
    def _apply_difficulty(self, difficulty: Optional[str]) -> None:
        """Configure shock strength/cooldown based on difficulty label."""
        level = (difficulty or "Normal").strip().lower()
        if level == "easy":
            self._shock_strength_min = 5
            self._shock_strength_max = 30
            self._cooldown_seconds = 8.0
        elif level == "hard":
            self._shock_strength_min = 30
            self._shock_strength_max = 100
            self._cooldown_seconds = 2.0

    def _thread_factory(self):
        import threading

        return threading.Thread(
            target=self._worker_loop,
            name="TrainerProximityFeature",
            daemon=True,
        )

    def _worker_loop(self) -> None:
        """Poll proximity parameter and trigger shocks when too far."""
        import time

        while not self._stop_event.is_set():
            now = time.time()

            # Rate-limit shocks.
            if now >= self._cooldown_until and self._is_too_far(now):
                self._deliver_correction()
                self._cooldown_until = now + self._cooldown_seconds
                self._breach_started_at = None

            if self._stop_event.wait(self._poll_interval):
                break

    def _is_too_far(self, now: float) -> bool:
        """Return True if proximity has been below threshold long enough."""
        value = self.osc.get_float_param("Trainer/Proximity", default=1.0)

        if value >= self._proximity_threshold:
            self._breach_started_at = None
            return False

        if self._breach_started_at is None:
            self._breach_started_at = now
            return False

        return (now - self._breach_started_at) >= self._breach_duration

    def _deliver_correction(self) -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            # Scale intensity by how far away the pet is.
            proximity = self.osc.get_float_param("Trainer/Proximity", default=0.0)
            distance_factor = max(0.0, (self._proximity_threshold - proximity) / self._proximity_threshold)
            strength = max(self._shock_strength_min, min(self._shock_strength_max, int(distance_factor * self._shock_strength_max)))
            self.pishock.send_shock(strength=strength, duration=0.5)
        except Exception:
            return
