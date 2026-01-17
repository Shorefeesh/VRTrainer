from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List

from logic.feature import PetFeature


class _PendingCommand:
    """Lightweight container for a command that is waiting to be completed."""

    def __init__(self, name: str, started_at: float, deadline: float) -> None:
        self.name = name
        self.started_at = started_at
        self.deadline = deadline


@dataclass
class _TrainerTrickState:
    pending: _PendingCommand | None = None
    cooldown_until: float = 0.0


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

        self._state_by_trainer: Dict[str, _TrainerTrickState] = {}

        self._base_command_timeout: float = 10.0

        self._command_phrases: dict[str, list[str]] = {
            "paw": ["paw", "poor", "pour", "pore"],
            "sit": ["sit"],
            "lay_down": ["lay down", "laydown", "lie down", "layed down"],
            "beg": ["beg"],
            "play_dead": ["play dead", "playdead", "played dead"],
            "roll_over": ["rollover", "roll over"],
            "present": ["present", "bend over", "ass up"],
        }

        self._log("init")

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetTricksFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():

            now = time.time()

            active_configs = self._active_trainer_configs()
            self._prune_inactive_states(active_configs)

            if not self._has_active_trainer():
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            command_events = self._collect_trick_events()

            for trainer_id, config in active_configs.items():
                state = self._state_by_trainer.setdefault(trainer_id, _TrainerTrickState())

                if state.pending is None and command_events.get(trainer_id):
                    self._maybe_start_command(now, state, command_events[trainer_id][0], config, trainer_id)

                if state.pending is not None:
                    if self._is_command_completed(state.pending.name):
                        self._log(
                            f"command_success trainer={trainer_id[:8]} trick={state.pending.name} duration={now - state.pending.started_at:.2f}"
                        )
                        self._deliver_completion_signal()
                        state.pending = None
                    elif now >= state.pending.deadline and now >= state.cooldown_until:
                        self._deliver_failure(trainer_id, config, state.pending)
                        state.cooldown_until = now + self._cooldown_seconds(config)
                        state.pending = None

            if self._stop_event.wait(self._poll_interval):
                break

    def _prune_inactive_states(self, active_configs: Dict[str, dict]) -> None:
        for trainer_id in list(self._state_by_trainer.keys()):
            if trainer_id not in active_configs:
                self._state_by_trainer.pop(trainer_id, None)

    def _collect_trick_events(self) -> Dict[str, List[dict]]:
        if self.server is None:
            return {}

        events = self.server.poll_feature_events(self.feature_name, limit=10)

        grouped: Dict[str, List[dict]] = {}
        for event in events:
            trainer_id = str(event.get("from_client") or "")
            if trainer_id:
                grouped.setdefault(trainer_id, []).append(event)
        return grouped

    def _maybe_start_command(self, now: float, state: _TrainerTrickState, event: dict, config: dict, trainer_id: str) -> None:
        payload = event.get("payload", {})
        name = payload.get("phrase")
        if not name:
            return

        normalised = self.normalise_text(str(name))
        if normalised not in self._command_phrases:
            return

        state.pending = _PendingCommand(
            name=normalised,
            started_at=now,
            deadline=now + self._command_timeout(config),
        )
        self._log(f"command_start trainer={trainer_id[:8]} trick={normalised}")
        self._deliver_task_start_signal()

    def _is_command_completed(self, command: str) -> bool:
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

    def _deliver_failure(self, trainer_id: str, config: dict, pending: _PendingCommand | None) -> None:
        try:
            strength, duration = self._shock_params(config)
            self.pishock.send_shock(strength=strength, duration=duration)
            self._log(
                f"task_fail_shock trainer={trainer_id[:8]} trick={pending.name if pending else 'unknown'} strength={strength}"
            )
        except Exception:
            return

    def _deliver_task_start_signal(self) -> None:
        try:
            self.pishock.send_vibrate(strength=10, duration=0.2)
            self._log("task_start_vibrate strength=10")
        except Exception:
            return

    def _deliver_completion_signal(self) -> None:
        try:
            for pulse in (1, 2):
                self.pishock.send_vibrate(strength=10, duration=0.2)
                self._log(f"task_complete_vibrate pulse={pulse} strength=10")
                if pulse == 1:
                    time.sleep(0.2)
        except Exception:
            return

    def _command_timeout(self, config: dict) -> float:
        scaling = self._scaling_from_config(config)
        return max(0.0, self._base_command_timeout * scaling["delay_scale"])

    def _shock_params(self, config: dict) -> tuple[int, float]:
        strength, duration = self._shock_params_single(config)
        return int(strength), duration
