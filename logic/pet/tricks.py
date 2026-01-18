from __future__ import annotations

import time
from typing import Dict, List

from logic.pet.feature import PetFeature


class TricksFeature(PetFeature):
    """Pet tricks feature.

    Runs on the pet client: reacts to trainer-issued commands delivered
    over the server and validates completion locally via OSC. The
    feature iterates per trainer config to allow multiple trainers in a
    session without local toggles.
    """

    feature_name = "tricks"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._base_delay_seconds: float = 10.0
        self._active_command: str = None

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetTricksFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._has_active_trainer():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            now = time.time()

            active_configs = self._active_trainer_configs()
            command_events = self._collect_events()

            for trainer_id, config in active_configs.items():
                if self._active_command is None and command_events.get(trainer_id):
                    self._start_command(now, command_events[trainer_id][0], config, trainer_id)

                if self._active_command is not None:
                    if self._is_command_completed():
                        self._log(
                            f"command_success trainer={trainer_id[:8]} trick={self._active_command} remaining={self._delay_until - now}"
                        )
                        self._deliver_task_completion_signal(config=config, trainer_id=trainer_id)
                        self._active_command = None
                    elif now >= self._delay_until:
                        self._deliver_shock_single(config=config, reason=self._active_command, trainer_id=trainer_id)

            if self._stop_event.wait(self._poll_interval):
                break

    def _start_command(self, now: float, event: dict, config: dict, trainer_id: str) -> None:
        command = event.get("payload").get("command")
        self._active_command = command,
        self._delay_until = now + self._scaled_delay(config)
        self._log(f"command_start trainer={trainer_id[:8]} trick={command}")
        self._deliver_task_start_signal(config, trainer_id)

    def _is_command_completed(self) -> bool:
        command = self._active_command
        if command == "paw":
            return (not self.osc.get_bool_param("Trainer/HandFloorLeftMin", default=False) \
                   or not self.osc.get_bool_param("Trainer/HandFloorRightMin", default=False)) \
                   and self.osc.get_bool_param("Trainer/FootFloorLeftMax", default=False) \
                   and self.osc.get_bool_param("Trainer/FootFloorRightMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsFloorMax", default=False) \
                   and not self.osc.get_bool_param("Trainer/HeadFloorMin", default=False)
        elif command == "sit":
            return self.osc.get_bool_param("Trainer/HandFloorLeftMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HandFloorRightMax", default=False) \
                   and self.osc.get_bool_param("Trainer/FootFloorLeftMax", default=False) \
                   and self.osc.get_bool_param("Trainer/FootFloorRightMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsFloorMax", default=False) \
                   and not self.osc.get_bool_param("Trainer/HeadFloorMin", default=False)
        elif command == "lay_down":
            return self.osc.get_bool_param("Trainer/HandFloorLeftMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HandFloorRightMax", default=False) \
                   and self.osc.get_bool_param("Trainer/FootFloorLeftMax", default=False) \
                   and self.osc.get_bool_param("Trainer/FootFloorRightMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsFloorMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadFloorMax", default=False)
        elif command == "beg":
            return not self.osc.get_bool_param("Trainer/HandFloorLeftMin", default=False) \
                   and not self.osc.get_bool_param("Trainer/HandFloorRightMin", default=False) \
                   and self.osc.get_bool_param("Trainer/FootFloorLeftMax", default=False) \
                   and self.osc.get_bool_param("Trainer/FootFloorRightMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsFloorMax", default=False) \
                   and not self.osc.get_bool_param("Trainer/HeadFloorMin", default=False)
        elif command == "play_dead":
            return not self.osc.get_bool_param("Trainer/HandFloorLeftMin", default=False) \
                   and not self.osc.get_bool_param("Trainer/HandFloorRightMin", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootFloorLeftMin", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootFloorRightMin", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsFloorMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadFloorMax", default=False)
        elif command == "roll_over":
            return not self.osc.get_bool_param("Trainer/HandFloorLeftMin", default=False) \
                   and not self.osc.get_bool_param("Trainer/HandFloorRightMin", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootFloorLeftMin", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootFloorRightMin", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsFloorMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadFloorMax", default=False)
        elif command == "present":
            return self.osc.get_bool_param("Trainer/HandFloorLeftMax", default=False) \
                   and self.osc.get_bool_param("Trainer/HandFloorRightMax", default=False) \
                   and self.osc.get_bool_param("Trainer/FootFloorLeftMax", default=False) \
                   and self.osc.get_bool_param("Trainer/FootFloorRightMax", default=False) \
                   and not self.osc.get_bool_param("Trainer/HipsFloorMin", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadFloorMax", default=False)

        return False

    def _deliver_task_start_signal(self, config: dict, trainer_id: str) -> None:
        self._deliver_vibrate_single(config=config, reason="task_start", trainer_id=trainer_id)

    def _deliver_task_completion_signal(self, config: dict, trainer_id: str) -> None:
        for pulse in (1, 2):
            self._deliver_vibrate_single(config=config, reason=f"task_complete_pulse{pulse}", trainer_id=trainer_id)
            if pulse == 1:
                time.sleep(0.2)
