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

        self._depth_threshold: float = 0.9
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

            config = list(self._active_trainer_configs().values())[0]

            if now >= self._cooldown_until:
                if self._check_and_maybe_shock(config):
                    self._cooldown_until = now + self._scaled_cooldown(config)

            if self._stop_event.wait(self._poll_interval):
                break

    def _check_and_maybe_shock(self, config: dict) -> bool:
        """Return True if a shock was sent based on current parameters."""
        for base in self._targets:
            depth = self.osc.get_bool_param(f"{base}")

            if depth >= self._depth_threshold:
                self._deliver_correction(base, depth, config)
                return True

        return False

    def _deliver_correction(self, target: str, depth: float, config: dict) -> None:
        """Trigger a corrective shock via PiShock."""
        shock_min, shock_max, shock_duration = self._shock_params_range(config)
        scale = (depth - self._depth_threshold) / (1 - self._depth_threshold)
        strength = max(shock_min, min(shock_max, scale * shock_max))

        self.pishock.send_shock(strength=strength, duration=shock_duration)
        self._log(
            f"shock target={target} depth={depth:.2f} threshold={self._depth_threshold:.2f} strength={strength:.1f}"
        )
