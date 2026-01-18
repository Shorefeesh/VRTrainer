from __future__ import annotations

from logic.pet.feature import PetFeature


class RemoteFeature(PetFeature):
    """Pet remote feature.

    Runs on the pet client: reacts to trainer-issued commands delivered
    over the server.
    """

    feature_name = "remote"

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetRemoteFeature")

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
            all_events = self._collect_events()

            for trainer_id, config in active_configs.items():
                trainer_events = all_events.get(trainer_id)
                if trainer_events:
                    for event in trainer_events:
                        command = event.get("payload").get("command")
                        if command == "shock":
                            self._deliver_shock_single(config=config, reason="shock", trainer_id=trainer_id)
                        elif command == "vibrate":
                            self._deliver_vibrate_single(config=config, reason="vibrate", trainer_id=trainer_id)

            if self._stop_event.wait(self._poll_interval):
                break
