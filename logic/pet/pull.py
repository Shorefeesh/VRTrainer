from __future__ import annotations

from logic.pet.feature import PetFeature


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
        while not self._stop_event.is_set():
            if not self._has_active_trainer():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            config = list(self._active_trainer_configs().values())[0]

            for base in self._targets:
                is_grabbed = self.osc.get_bool_param(f"{base}_IsGrabbed")
                stretch = self.osc.get_float_param(f"{base}_Stretch")

                if is_grabbed:
                    self._log_sample({"bone": base, "stretch": stretch})
                    if stretch >= self._stretch_threshold:
                        self._deliver_shock_range(config=config, reason=base, value=stretch, threshold=self._stretch_threshold)

            if self._stop_event.wait(self._poll_interval):
                break
