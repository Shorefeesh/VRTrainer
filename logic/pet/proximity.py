from __future__ import annotations

from typing import Dict, List

from logic.pet.feature import PetFeature


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

        self._pending_command_from: str = None

        self._proximity_threshold: float = 0.4
        self._heel_proximity_target: float = 1

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetProximityFeature")

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

            summon_events = self._collect_remote_summons()

            proximity_value = self.osc.get_float_param("Trainer/Proximity", default=1.0)

            self._log_sample({"proximity": proximity_value})

            for trainer_id, config in active_configs.items():
                if summon_events.get(trainer_id):
                    self._pending_command_from = trainer_id
                    self._delay_until = now + self._scaled_delay(config)
                    self._log(
                        f"summon_start trainer={trainer_id[:8]}"
                    )

                if self._pending_command_from is not None:
                    if proximity_value >= self._heel_proximity_target:
                        self._delay_until = None
                        self._log(
                            f"summon_success trainer={trainer_id[:8]} proximity={proximity_value:.3f}"
                        )
                        self._pending_command_from = None
                    elif now >= self._delay_until:
                        self._deliver_shock_single(config=config, reason="didnt_heel", trainer_id=trainer_id)

            config = list(self._active_trainer_configs().values())[0]

            if now >= self._cooldown_until and proximity_value <= self._proximity_threshold:
                self._deliver_shock_range(config=config, reason="too_far", value=proximity_value, threshold=self._proximity_threshold, min=0, inverse=True)

            if self._stop_event.wait(self._poll_interval):
                break

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
