from __future__ import annotations

from dataclasses import dataclass, field
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

        self._state_by_trainer: Dict[str, _TrainerFocusState] = {}

        # Focus meter state and tunables.
        self._poll_interval: float = 0.1
        self._fill_rate: float = 0.2
        self._drain_rate: float = 0.02
        self._shock_threshold: float = 0.2

        self._name_penalty: float = 0.15

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
            self._prune_inactive_states(active_configs)

            penalties = self._collect_focus_events()

            for trainer_id, config in active_configs.items():
                state = self._state_by_trainer.setdefault(trainer_id, _TrainerFocusState(now))
                dt = max(0.0, now - state.last_tick)
                state.last_tick = now

                self._apply_remote_penalties_for_trainer(trainer_id, state, penalties.get(trainer_id, []))
                self._update_meter(state, dt)
                self._log_sample(now, trainer_id, state)

                if self._should_shock(now, state):
                    self._deliver_correction(trainer_id, state, config)
                    state.cooldown_until = now + self._cooldown_seconds(config)

            if self._stop_event.wait(self._poll_interval):
                break

    def _prune_inactive_states(self, active_configs: Dict[str, dict]) -> None:
        for trainer_id in list(self._state_by_trainer.keys()):
            if trainer_id not in active_configs:
                self._state_by_trainer.pop(trainer_id, None)

    def _collect_focus_events(self) -> Dict[str, List[dict]]:
        if self.server is None:
            return {}

        events = self.server.poll_feature_events(self.feature_name, limit=10)

        grouped: Dict[str, List[dict]] = {}
        for event in events:
            trainer_id = str(event.get("from_client") or "")
            if trainer_id:
                grouped.setdefault(trainer_id, []).append(event)
        return grouped

    def _update_meter(self, state: "_TrainerFocusState", dt: float) -> None:
        focused = self.osc.get_bool_param("Trainer/EyeLeft", default=True) \
          or self.osc.get_bool_param("Trainer/EyeFarLeft", default=False) \
          or self.osc.get_bool_param("Trainer/EyeRight", default=True) \
          or self.osc.get_bool_param("Trainer/EyeFarRight", default=False) \
          or self.osc.get_bool_param("Trainer/ProximityHead", default=False)
        delta = (self._fill_rate if focused else -self._drain_rate) * dt
        state.focus_meter = max(0.0, min(1.0, state.focus_meter + delta))

    def _apply_remote_penalties_for_trainer(self, trainer_id: str, state: "_TrainerFocusState", events: List[dict]) -> None:
        if not events:
            return

        state.last_command_trainer = trainer_id or state.last_command_trainer
        for _event in events:
            state.focus_meter = max(0.0, state.focus_meter - self._name_penalty)

    def _should_shock(self, now: float, state: "_TrainerFocusState") -> bool:
        if now < state.cooldown_until:
            return False
        return state.focus_meter <= self._shock_threshold

    def _deliver_correction(self, trainer_id: str, state: "_TrainerFocusState", config: dict) -> None:
        try:
            shock_min, shock_max, shock_duration = self._shock_params_range(config)
            deficit = (self._shock_threshold - state.focus_meter) / self._shock_threshold
            strength = max(shock_min, min(shock_max, int(deficit * shock_max)))
            self.pishock.send_shock(strength=strength, duration=shock_duration)
            self._log(
                f"event=shock feature=focus runtime=pet trainer={trainer_id[:8]} meter={state.focus_meter:.3f} threshold={self._shock_threshold:.3f} strength={strength}"
            )
            self._send_logs(
                {
                    "event": "shock",
                    "meter": state.focus_meter,
                    "threshold": self._shock_threshold,
                    "strength": strength,
                },
                target_clients=[trainer_id],
            )
        except Exception:
            return

    def _log_sample(self, now: float, trainer_id: str, state: "_TrainerFocusState") -> None:
        if now - state.last_sample_log < 1.0:
            return

        state.last_sample_log = now
        self._log(
            f"event=sample feature=focus runtime=pet trainer={trainer_id[:8]} meter={state.focus_meter:.3f} threshold={self._shock_threshold:.3f}"
        )
        self._send_logs(
            {
                "event": "sample",
                "meter": state.focus_meter,
                "threshold": self._shock_threshold,
            },
            target_clients=[trainer_id],
        )


@dataclass
class _TrainerFocusState:
    last_tick: float = field(default_factory=lambda: 0.0)
    focus_meter: float = 1.0
    cooldown_until: float = 0.0
    last_sample_log: float = 0.0
    last_command_trainer: str | None = None
