from __future__ import annotations

from logic.feature import PetFeature


class PullFeature(PetFeature):
    """Pet ear/tail pull feature.

    Uses OSC parameters to track ear/tail stretch and PiShock to apply
    feedback when limits are exceeded.
    """

    feature_name = "pull"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._stretch_threshold: float = 0.5
        self._targets = ("LeftEar", "RightEar", "Tail")

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetPullFeature")

    def stop(self) -> None:
        self._stop_worker()

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

            config = list(self._active_trainer_configs().values())[0]

            if now >= self._cooldown_until:
                if self._check_and_maybe_shock(now, config):
                    self._cooldown_until = now + self._scaled_cooldown()

            if self._stop_event.wait(self._poll_interval):
                break

    def _check_and_maybe_shock(self, now: float, config: dict) -> bool:
        """Return True if a shock was sent based on current parameters."""
        for base in self._targets:
            is_grabbed = self.osc.get_bool_param(f"{base}_IsGrabbed")
            stretch = self.osc.get_float_param(f"{base}_Stretch")

            if is_grabbed and stretch >= self._stretch_threshold:
                self._deliver_correction(base, stretch, config)
                return True

        return False

    def _deliver_correction(self, target: str, stretch: float, config: dict) -> None:
        """Trigger a corrective shock via PiShock."""
        shock_min, shock_max, shock_duration = self._shock_params_range(config)
        scale = (stretch - self._stretch_threshold) / (1 - self._stretch_threshold)
        strength = max(shock_min, min(shock_max, scale * shock_max))

        self.pishock.send_shock(strength=strength, duration=shock_duration)
        self._log(
            f"event=shock feature=pull target={target} stretch={stretch:.2f} threshold={self._stretch_threshold:.2f} strength={strength:.1f}"
        )
