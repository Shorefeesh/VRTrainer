from __future__ import annotations

import threading

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import RemoteServerInterface
from logic.logging_utils import LogFile


class PullFeature:
    """Pet ear/tail pull feature.

    Uses OSC parameters to track ear/tail stretch and PiShock to apply
    feedback when limits are exceeded.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        server: RemoteServerInterface | None = None,
        logger: LogFile | None = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.server = server
        self._logger = logger
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

        self._shock_strength_min: float = 20.0
        self._shock_strength_max: float = 40.0

        # Parameter base names for ears and tail.
        self._targets = ("LeftEar", "RightEar", "Tail")

        self._log("event=init feature=pull")

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

        self._log("event=start feature=pull")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=pull")

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        """Background loop that watches ear/tail stretch parameters."""
        import time

        while not self._stop_event.is_set():
            if not self._has_active_trainer():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            now = time.time()

            # Avoid sending multiple shocks in quick succession when
            # the avatar reports a sustained pull.
            if now >= self._cooldown_until:
                if self._check_and_maybe_shock(now):
                    self._cooldown_until = now + self._cooldown_seconds

            if self._stop_event.wait(self._poll_interval):
                break

    def _has_active_trainer(self) -> bool:
        server = self.server
        if server is None:
            return False

        configs = getattr(server, "latest_settings_by_trainer", lambda: {})()
        return any(cfg.get("feature_ear_tail") for cfg in configs.values())

    def _check_and_maybe_shock(self, now: float) -> bool:
        """Return True if a shock was sent based on current parameters."""
        for base in self._targets:
            is_grabbed = self.osc.get_bool_param(f"{base}_IsGrabbed")
            stretch = self.osc.get_float_param(f"{base}_Stretch")

            if is_grabbed and stretch >= self._stretch_threshold:
                self._deliver_correction(base, stretch)
                return True

        return False

    def _deliver_correction(self, target: str, stretch: float) -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            # Scale intensity slightly with stretch so gentle pulls are
            # milder than extreme ones.
            scale = (stretch - self._stretch_threshold) / (1 - self._stretch_threshold)
            strength = max(self._shock_strength_min, min(self._shock_strength_max, scale * self._shock_strength_max))

            self.pishock.send_shock(strength=strength, duration=0.5)
            self._log(
                f"event=shock feature=pull target={target} stretch={stretch:.2f} threshold={self._stretch_threshold:.2f} strength={strength:.1f}"
            )
        except Exception:
            # Never let PiShock errors break the feature loop.
            return

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return
