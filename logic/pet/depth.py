from __future__ import annotations


from logic.feature import PetFeature


class DepthFeature(PetFeature):
    """Pet SPS depth feature.

    Uses OSC parameters to track SPS depth and PiShock to apply
    feedback when limits are exceeded.
    """

    feature_name = "depth"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._depth_threshold: float = 0.5
        self._poll_interval: float = 0.1

        self._shock_strength_min: float = 20.0
        self._shock_strength_max: float = 40.0

        # Parameter base names for depth receivers.
        self._targets = ("Trainer/PenDepth")

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetDepthFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        """Background loop that watches depth parameters."""
        import time

        while not self._stop_event.is_set():
            if not self._has_active_trainer():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            now = time.time()

            # Avoid sending multiple shocks in quick succession when
            # the avatar reports a sustained depth.
            if now >= self._cooldown_until:
                if self._check_and_maybe_shock(now):
                    self._cooldown_until = now + self._cooldown_seconds

            if self._stop_event.wait(self._poll_interval):
                break

    def _check_and_maybe_shock(self, now: float) -> bool:
        """Return True if a shock was sent based on current parameters."""
        for base in self._targets:
            depth = self.osc.get_bool_param(f"{base}")

            if depth >= self._stretch_threshold:
                self._deliver_correction(base, depth)
                return True

        return False

    def _deliver_correction(self, target: str, depth: float) -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            # Scale intensity slightly with depth so shallow is
            # milder than deep ones.
            scale = (depth - self._depth_threshold) / (1 - self._depth_threshold)
            strength = max(self._shock_strength_min, min(self._shock_strength_max, scale * self._shock_strength_max))

            self.pishock.send_shock(strength=strength, duration=0.5)
            self._log(
                f"event=shock feature=depth target={target} depth={depth:.2f} threshold={self._depth_threshold:.2f} strength={strength:.1f}"
            )
        except Exception:
            # Never let PiShock errors break the feature loop.
            return
