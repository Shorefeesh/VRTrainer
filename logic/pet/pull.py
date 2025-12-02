from __future__ import annotations

import threading

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface


class PullFeature:
    """Pet ear/tail pull feature.

    Uses OSC parameters to track ear/tail stretch and PiShock to apply
    feedback when limits are exceeded.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        whisper: WhisperInterface,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self._running = False

        # Background worker that polls OSC parameters.
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Simple configuration – can be made user-adjustable later.
        # Stretch values are floats in the 0–1 range.
        self._stretch_threshold: float = 0.5
        self._poll_interval: float = 0.1
        self._cooldown_seconds: float = 2.0
        self._cooldown_until: float = 0.0

        # Parameter base names for ears and tail.
        self._targets = ("LeftEar", "RightEar", "Tail")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        thread = threading.Thread(
            target=self._worker_loop,
            name="PetPullFeature",
            daemon=True,
        )
        self._thread = thread
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
    def _worker_loop(self) -> None:
        """Background loop that watches ear/tail stretch parameters."""
        import time

        while not self._stop_event.is_set():
            now = time.time()

            # Avoid sending multiple shocks in quick succession when
            # the avatar reports a sustained pull.
            if now >= self._cooldown_until:
                if self._check_and_maybe_shock(now):
                    self._cooldown_until = now + self._cooldown_seconds

            if self._stop_event.wait(self._poll_interval):
                break

    def _check_and_maybe_shock(self, now: float) -> bool:
        """Return True if a shock was sent based on current parameters."""
        for base in self._targets:
            is_grabbed = self._get_bool_param(f"{base}_IsGrabbed")
            stretch = self._get_float_param(f"{base}_Stretch")

            if is_grabbed and stretch >= self._stretch_threshold:
                self._deliver_correction(base, stretch)
                return True

        return False

    def _get_bool_param(self, name: str) -> bool:
        """Interpret an OSC parameter as a boolean."""
        raw = self.osc.get_parameter(name)
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

    def _get_float_param(self, name: str) -> float:
        """Interpret an OSC parameter as a float in the 0–1 range."""
        raw = self.osc.get_parameter(name)
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

    def _deliver_correction(self, target: str, stretch: float) -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            # Scale intensity slightly with stretch so gentle pulls are
            # milder than extreme ones.
            base_strength = 20
            extra = int((stretch - self._stretch_threshold) * 80)
            strength = max(10, min(100, base_strength + extra))

            self.pishock.send_shock(strength=strength, duration=0.5)
        except Exception:
            # Never let PiShock errors break the feature loop.
            return
