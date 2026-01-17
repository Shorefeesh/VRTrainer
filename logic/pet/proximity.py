from __future__ import annotations

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

        self._pending_command_from: str = None

        self._poll_interval: float = 0.1
        self._proximity_threshold: float = 0.4
        self._command_target: float = 1
        self._last_sample_log: float = 0

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

            self._log_sample(now, proximity_value)

            for trainer_id, config in active_configs.items():
                if summon_events.get(trainer_id):
                    self._pending_command_from = trainer_id
                    self._command_until = now + self._scaled_delay(config)
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

                if self._pending_command_from is not None:
                    if self._meets_command_target(proximity_value):
                        self._command_until = None
                        self._log(
                            f"summon_success trainer={trainer_id[:8]} proximity={proximity_value:.3f}"
                        )
                        self._send_logs(
                            {
                                "event": "command_success",
                                "name": "summon",
                                "proximity": proximity_value,
                            },
                            target_clients=[self._pending_command_from],
                        )
                        self._pending_command_from = None
                    elif now >= self._command_until and now >= self._cooldown_until:
                        self._deliver_correction(
                            trainer_id,
                            config,
                            "summon command missed",
                            proximity_value,
                            target_client=self._pending_command_from,
                        )
                        self._cooldown_until = now + self._scaled_cooldown(config)
                        self._command_until = None
                        self._pending_command_from = None

                if now >= self._cooldown_until and proximity_value <= self._proximity_threshold:
                    self._deliver_correction(
                        trainer_id,
                        config,
                        "too far from trainer",
                        proximity_value,
                        broadcast_trainers=True,
                    )
                    self._cooldown_until = now + self._scaled_cooldown(config)


            if self._stop_event.wait(self._poll_interval):
                break

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
            shock_min, shock_max, shock_duration = self._shock_params_range(config)
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

    def _log_sample(self, now: float, proximity_value: float) -> None:
        if now - self._last_sample_log < 1.0:
            return

        self._last_sample_log = now
        self._log(
            f"sample proximity={proximity_value:.3f} threshold={self._proximity_threshold:.3f}"
        )
        stats = {
                "event": "sample",
                "proximity": proximity_value,
                "threshold": self._proximity_threshold,
            }
        self._send_logs(stats)
