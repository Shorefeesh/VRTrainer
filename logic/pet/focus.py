from __future__ import annotations

from typing import Dict, List

from logic.pet.feature import PetFeature


class FocusFeature(PetFeature):
    """Pet focus feature.

    Runs on the pet client, reading OSC eye-contact parameters and
    delivering shocks locally when focus drops too low.
    """

    feature_name = "focus"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._fill_rate: float = 0.2
        self._drain_rate: float = 0.02
        self._focus_shock_threshold: float = 0.2
        self._name_penalty: float = 0.15
        self._focus_meter: float = 1.0
        self._last_tick: float = 0

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetFocusFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        import time

        while not self._stop_event.is_set():
            if not self._has_active_trainer():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            now = time.time()

            config = list(self._active_trainer_configs().values())[0]

            penalties = self._collect_focus_events()
            self._apply_penalties(penalties)

            dt = max(0.0, now - self._last_tick)
            self._update_meter(dt)
            self._last_tick = now

            if self._should_shock():
                self._deliver_shock_range(config=config, reason="focus_low", value=self._focus_meter, threshold=self._focus_shock_threshold, inverse=True)

            self._log_sample({"meter": self._focus_meter, "threshold": self._focus_shock_threshold})

            if self._stop_event.wait(self._poll_interval):
                break

    def _collect_focus_events(self) -> Dict[str, List[dict]]:
        return self.server.poll_feature_events(self.feature_name, limit=10)

    def _update_meter(self, dt: float) -> None:
        focused = self.osc.get_bool_param("Trainer/EyeLeft", default=True) \
          or self.osc.get_bool_param("Trainer/EyeFarLeft", default=False) \
          or self.osc.get_bool_param("Trainer/EyeRight", default=True) \
          or self.osc.get_bool_param("Trainer/EyeFarRight", default=False) \
          or self.osc.get_bool_param("Trainer/ProximityHead", default=False)
        delta = (self._fill_rate if focused else -self._drain_rate) * dt
        self._focus_meter = max(0.0, min(1.0, self._focus_meter + delta))

    def _apply_penalties(self, events: List[dict]) -> None:
        self._focus_meter = max(0.0, self._focus_meter - (len(events) if events else 0) * self._name_penalty)

    def _should_shock(self) -> bool:
        return self._focus_meter <= self._focus_shock_threshold
