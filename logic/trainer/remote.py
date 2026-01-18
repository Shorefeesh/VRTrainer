from __future__ import annotations


from logic.trainer.feature import TrainerFeature


class TrainerRemoteFeature(TrainerFeature):
    """Trainer-side OSC listener for manual shock/vibrate menu trigger."""

    feature_name: str = "remote"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._prev_shock: bool = False
        self._prev_vibrate: bool = False

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="TrainerProximityFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._has_active_pet():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            pet_configs = self._config_map()
            for pet_id, cfg in pet_configs.items():
                if not cfg.get(self.feature_name):
                    continue

                shock_trigger = self.osc.get_bool_param(f"Trainer/Menu/Shock", False)
                if shock_trigger and not self._prev_shock:
                    meta = {"feature": self.feature_name, "target_client": str(pet_id)}
                    self.server.send_command("shock", meta)

                vibrate_trigger = self.osc.get_bool_param(f"Trainer/Menu/Vibrate", False)
                if vibrate_trigger and not self._prev_vibrate:
                    meta = {"feature": self.feature_name, "target_client": str(pet_id)}
                    self.server.send_command("vibrate", meta)

                self._prev_shock = shock_trigger
                self._prev_vibrate = vibrate_trigger

            if self._stop_event.wait(self._poll_interval):
                break
