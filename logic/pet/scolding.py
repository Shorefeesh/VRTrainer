from __future__ import annotations

import time
from typing import Dict, List

from logic.pet.feature import PetFeature


class ScoldingFeature(PetFeature):
    """Pet scolding feature.

    Listens for scolding commands from each trainer in the session.
    Config for the trainer (word lists, scaling) is supplied via the
    server; the pet only applies what it receives over the network.
    """

    feature_name = "scolding"

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

            events_by_trainer = self._collect_events()

            for trainer_id, config in active_configs.items():
                if events_by_trainer.get(trainer_id):
                    self._deliver_shock_single(config=config, reason="scold", trainer_id=trainer_id)

            if self._stop_event.wait(self._poll_interval):
                break
