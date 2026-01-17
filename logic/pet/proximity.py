from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from logic.feature import PetFeature


class ProximityFeature(PetFeature):
    """Pet proximity feature.

    Evaluates distance to each trainer in the active session using the
    per-trainer config delivered over the server. All logic runs locally
    but settings originate from the assigned trainer profile.
    """

    feature_name = "proximity"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._state_by_trainer: Dict[str, _TrainerProximityState] = {}

        # Tunables shared by all trainers; per-trainer scaling applied on the fly.
        self._poll_interval: float = 0.1
        self._proximity_threshold: float = 0.4
        self._command_target: float = 1

        self._log("event=init feature=proximity runtime=pet")

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetProximityFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        import time

        while not self._stop_event.is_set():
            now = time.time()

            active_configs = self._active_trainer_configs()
            self._prune_inactive_states(active_configs)

            if not self._has_active_trainer():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            summon_events = self._collect_remote_summons()

            proximity_value = self.osc.get_float_param("Trainer/Proximity", default=1.0)

            for trainer_id, config in active_configs.items():
                state = self._state_by_trainer.setdefault(trainer_id, _TrainerProximityState())

                if summon_events.get(trainer_id):
                    state.pending_command_from = trainer_id
                    state.pending_command_deadline = now + self._scaled_timeout(config)
                    self._log(
                        f"summon_start trainer={trainer_id[:8]}"
                    )
                    self._send_logs(
                        {
                            "event": "command_start",
                            "name": "summon",
                        },
                        target_clients=[trainer_id],
                    )

                if state.pending_command_deadline is not None:
                    if self._meets_command_target(proximity_value):
                        state.pending_command_deadline = None
                        trainer_target = state.pending_command_from
                        state.pending_command_from = None
                        self._log(
                            f"summon_success trainer={trainer_id[:8]} proximity={proximity_value:.3f}"
                        )
                        self._send_logs(
                            {
                                "event": "command_success",
                                "name": "summon",
                                "proximity": proximity_value,
                            },
                            target_clients=[trainer_target],
                        )
                    elif now >= state.pending_command_deadline and now >= state.cooldown_until:
                        trainer_target = state.pending_command_from
                        state.pending_command_from = None
                        self._deliver_correction(
                            trainer_id,
                            config,
                            "summon command missed",
                            proximity_value,
                            target_client=trainer_target,
                        )
                        state.cooldown_until = now + self._scaled_cooldown(config)
                        state.pending_command_deadline = None

                if now >= state.cooldown_until and proximity_value <= self._proximity_threshold:
                    self._deliver_correction(
                        trainer_id,
                        config,
                        "too far from trainer",
                        proximity_value,
                        broadcast_trainers=True,
                    )
                    state.cooldown_until = now + self._scaled_cooldown(config)

                self._log_sample(now, trainer_id, state, proximity_value)

            if self._stop_event.wait(self._poll_interval):
                break

    def _prune_inactive_states(self, active_configs: Dict[str, dict]) -> None:
        for trainer_id in list(self._state_by_trainer.keys()):
            if trainer_id not in active_configs:
                self._state_by_trainer.pop(trainer_id, None)

    def _deliver_correction(
        self,
        trainer_id: str,
        config: dict,
        reason: str,
        proximity_value: float,
        *,
        target_client: str | None = None,
        broadcast_trainers: bool | None = None,
    ) -> None:
        try:
            shock_min, shock_max, shock_duration = self._shock_params(config)
            deficit = (self._proximity_threshold - proximity_value) / self._proximity_threshold
            strength = max(shock_min, min(shock_max, int(deficit * shock_max)))
            self.pishock.send_shock(strength=strength, duration=shock_duration)
            self._log(
                f"{reason.replace(' ', '_')}_shock trainer={trainer_id[:8]} proximity={proximity_value:.3f} threshold={self._proximity_threshold:.3f} strength={strength}"
            )
            target_client=target_client or trainer_id
            self._send_logs(
                {
                    "event": "shock",
                    "reason": reason,
                    "proximity": proximity_value,
                    "threshold": self._proximity_threshold,
                    "strength": strength,
                },
                target_clients=[target_client],
                broadcast_trainers=broadcast_trainers,
            )
        except Exception:
            return

    def _collect_remote_summons(self) -> Dict[str, List[dict]]:
        if self.server is None:
            return {}

        events = self.server.poll_feature_events("proximity", limit=10)

        grouped: Dict[str, List[dict]] = {}
        for event in events:
            trainer_id = str(event.get("from_client") or "")
            if trainer_id:
                grouped.setdefault(trainer_id, []).append(event)
        return grouped

    def _meets_command_target(self, proximity_value: float | None = None) -> bool:
        proximity = (
            proximity_value if proximity_value is not None else self.osc.get_float_param("Trainer/Proximity", default=0.0)
        )
        return proximity >= self._command_target

    def _log_sample(self, now: float, trainer_id: str, state: "_TrainerProximityState", proximity_value: float) -> None:
        if now - state.last_sample_log < 1.0:
            return

        state.last_sample_log = now
        self._log(
            f"sample trainer={trainer_id[:8]} value={proximity_value:.3f} threshold={self._proximity_threshold:.3f}"
        )
        stats = {
                "event": "sample",
                "value": proximity_value,
                "threshold": self._proximity_threshold,
            }
        self._send_logs(stats, [trainer_id])

    def _shock_params(self, config: dict) -> tuple[float, float, float]:
        return self._shock_params_range(config)


@dataclass
class _TrainerProximityState:
    cooldown_until: float = 0.0
    pending_command_deadline: float | None = None
    pending_command_from: str | None = None
    last_sample_log: float = field(default_factory=lambda: 0.0)
