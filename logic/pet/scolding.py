from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from logic.feature import PetFeature


class ScoldingFeature(PetFeature):
    """Pet scolding feature.

    Listens for scolding commands from each trainer in the session.
    Config for the trainer (word lists, scaling) is supplied via the
    server; the pet only applies what it receives over the network.
    """

    feature_name = "scolding"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._log("init")

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetScoldingFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._has_active_trainer():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            active_configs = self._active_trainer_configs()

            events_by_trainer = self._collect_scold_events()
            now = time.time()

            for trainer_id, config in active_configs.items():
                if events_by_trainer.get(trainer_id):
                    if now >= self._cooldown_until:
                        self._deliver_scolding_shock(trainer_id, config)
                        self._cooldown_until = now + self._scaled_cooldown(config)

            if self._stop_event.wait(0.5):
                break

    def _collect_scold_events(self) -> Dict[str, List[dict]]:
        if self.server is None:
            return {}

        events = self.server.poll_feature_events(self.feature_name, limit=10)

        grouped: Dict[str, List[dict]] = {}
        for event in events:
            trainer_id = str(event.get("from_client") or "")
            if trainer_id:
                grouped.setdefault(trainer_id, []).append(event)
        return grouped

    def _deliver_scolding_shock(self, trainer_id: str, config: dict) -> None:
        try:
            strength, duration = self._shock_params_single(config)
            self.pishock.send_shock(strength=strength, duration=duration)
            self._log(f"shock trainer={trainer_id[:8]} strength={strength}")
        except Exception:
            return
