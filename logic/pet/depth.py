from __future__ import annotations


from logic.pet.feature import PetFeature


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
        self._targets = [
            "OGB/Orf/Pussy/PenOthers",
            "OGB/Orf/Ass/PenOthers",
            "OGB/Orf/Mouth/PenOthers",
        ]

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetDepthFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        """Background loop that watches depth parameters."""
        while not self._stop_event.is_set():
            if not self._has_active_trainer():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            config = list(self._active_trainer_configs().values())[0]

            for base in self._targets:
                depth = self.osc.get_float_param(base)

                if depth > 0:
                    self._log_sample({"orifice": base, "depth": depth})

                if depth >= self._depth_threshold:
                    self._deliver_shock_range(config=config, reason=base, value=depth, threshold=self._depth_threshold)

            if self._stop_event.wait(self._poll_interval):
                break
