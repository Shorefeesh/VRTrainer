from __future__ import annotations

from typing import Dict, List

from logic.feature import PetFeature


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

        self._poll_interval: float = 0.1
        self._fill_rate: float = 0.2
        self._drain_rate: float = 0.02
        self._shock_threshold: float = 0.2
        self._name_penalty: float = 0.15
        self._focus_meter: float = 1.0
        self._last_sample_log: float = 0
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

            active_configs = self._active_trainer_configs()
            config = self._active_trainer_configs().values()[0]

            penalties = self._collect_focus_events()
            for trainer_id, config in active_configs.items():
                self._apply_penalties(trainer_id, penalties.get(trainer_id, []))

            dt = max(0.0, now - self._last_tick)
            self._update_meter(dt)
            self._last_tick = now

            if self._should_shock(now):
                self._deliver_correction(trainer_id, config)
                self._cooldown_until = now + self._scaled_cooldown(config)

            self._log_sample(now, trainer_id)

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

    def _apply_penalties(self, trainer_id: str, events: List[dict]) -> None:
        self._focus_meter = max(0.0, self._focus_meter - (len(events) if events else 0) * self._name_penalty)

    def _should_shock(self, now: float) -> bool:
        if now < self._cooldown_until:
            return False
        return self._focus_meter <= self._shock_threshold

    def _deliver_correction(self, trainer_id: str, config: dict) -> None:
        shock_min, shock_max, shock_duration = self._shock_params_range(config)
        deficit = (self._shock_threshold - self._focus_meter) / self._shock_threshold
        strength = max(shock_min, min(shock_max, int(deficit * shock_max)))
        self.pishock.send_shock(strength=strength, duration=shock_duration)
        self._log(
            f"event=shock trainer={trainer_id[:8]} meter={self._focus_meter:.3f} threshold={self._shock_threshold:.3f} strength={strength}"
        )
        self._send_logs(
            {
                "event": "shock",
                "meter": self._focus_meter,
                "threshold": self._shock_threshold,
                "strength": strength,
            },
            target_clients=[trainer_id],
        )

    def _log_sample(self, now: float, trainer_id: str) -> None:
        if now - self._last_sample_log < 1.0:
            return

        self._last_sample_log = now
        self._log(
            f"event=sample feature=focus runtime=pet trainer={trainer_id[:8]} meter={self._focus_meter:.3f} threshold={self._shock_threshold:.3f}"
        )
        # Rework per-trainer logs
        # self._send_logs(
        #     {
        #         "event": "sample",
        #         "meter": self._focus_meter,
        #         "threshold": self._shock_threshold,
        #     },
        #     target_clients=[trainer_id],
        # )
