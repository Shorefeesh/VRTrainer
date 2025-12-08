from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import RemoteServerInterface
from logic.logging_utils import LogFile


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


class TricksFeature:
    """Pet tricks feature.

    Runs on the pet client: reacts to trainer-issued commands delivered
    over the server and validates completion locally via OSC. The
    feature iterates per trainer config to allow multiple trainers in a
    session without local toggles.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        server: RemoteServerInterface | None = None,
        logger: LogFile | None = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.server = server
        self._logger = logger
        self._running = False

        import threading

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._state_by_trainer: Dict[str, _TrainerTrickState] = {}

        self._poll_interval: float = 0.2
        self._base_command_timeout: float = 5.0
        self._base_cooldown_seconds: float = 2.0
        self._base_shock_strength: float = 35
        self._base_shock_duration: float = 0.5

        self._command_phrases: dict[str, list[str]] = {
            "paw": ["paw", "poor", "pour", "pore"],
            "sit": ["sit"],
            "lay_down": ["lay down", "laydown", "lie down", "layed down"],
            "beg": ["beg"],
            "play_dead": ["play dead", "playdead", "played dead"],
            "roll_over": ["rollover", "roll over"],
        }

        self._log("event=init feature=tricks runtime=pet")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        import threading

        thread = self._thread = threading.Thread(
            target=self._worker_loop,
            name="PetTricksFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=tricks runtime=pet")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=tricks runtime=pet")

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()

            active_configs = self._active_trainer_configs()
            self._prune_inactive_states(active_configs)

            if not active_configs:
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
                            f"event=command_success feature=tricks runtime=pet trainer={trainer_id[:8]} name={state.pending.name} duration={now - state.pending.started_at:.2f}"
                        )
                        self._deliver_completion_signal()
                        state.pending = None
                    elif now >= state.pending.deadline and now >= state.cooldown_until:
                        self._deliver_failure(trainer_id, config, state.pending)
                        state.cooldown_until = now + self._cooldown_seconds(config)
                        state.pending = None

            if self._stop_event.wait(self._poll_interval):
                break

    def _active_trainer_configs(self) -> Dict[str, dict]:
        server = self.server
        if server is None:
            return {}
        raw_configs = getattr(server, "latest_settings_by_trainer", None)
        configs = raw_configs() if callable(raw_configs) else raw_configs
        if not isinstance(configs, dict):
            configs = {}
        return {tid: cfg for tid, cfg in configs.items() if cfg.get("feature_tricks")}

    def _prune_inactive_states(self, active_configs: Dict[str, dict]) -> None:
        for trainer_id in list(self._state_by_trainer.keys()):
            if trainer_id not in active_configs:
                self._state_by_trainer.pop(trainer_id, None)

    def _collect_trick_events(self) -> Dict[str, List[dict]]:
        if self.server is None:
            return {}

        events = self.server.poll_feature_events("tricks", limit=10)

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

        normalised = self._normalise_text(str(name))
        if normalised not in self._command_phrases:
            return

        state.pending = _PendingCommand(
            name=normalised,
            started_at=now,
            deadline=now + self._command_timeout(config),
        )
        self._log(f"event=command_start feature=tricks runtime=pet trainer={trainer_id[:8]} name={normalised}")
        self._deliver_task_start_signal()

    def _is_command_completed(self, command: str) -> bool:
        if command == "paw":
            return self.osc.get_bool_param("Trainer/Paw", default=False)
        elif command == "sit":
            return self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "lay_down":
            return self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "beg":
            return not self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "play_dead":
            return not self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "roll_over":
            return not self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)

        return False

    def _deliver_failure(self, trainer_id: str, config: dict, pending: _PendingCommand | None) -> None:
        try:
            strength, duration = self._shock_params(config)
            self.pishock.send_shock(strength=strength, duration=duration)
            self._log(
                f"event=shock feature=tricks runtime=pet trainer={trainer_id[:8]} name={pending.name if pending else 'unknown'} strength={strength}"
            )
        except Exception:
            return

    def _deliver_task_start_signal(self) -> None:
        try:
            self.pishock.send_vibrate(strength=10, duration=0.2)
            self._log("event=shock feature=tricks runtime=pet reason=task_start strength=1")
        except Exception:
            return

    def _deliver_completion_signal(self) -> None:
        try:
            for pulse in (1, 2):
                self.pishock.send_vibrate(strength=10, duration=0.2)
                self._log(f"event=shock feature=tricks runtime=pet reason=task_complete pulse={pulse} strength=1")
                if pulse == 1:
                    time.sleep(0.2)
        except Exception:
            return

    @staticmethod
    def _normalise_text(text: str) -> str:
        if not text:
            return ""

        chars: list[str] = []
        for ch in text.lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch == "_":
                chars.append("_")
            elif ch.isspace():
                chars.append(" ")
            else:
                chars.append(" ")

        return " ".join("".join(chars).split())

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return

    @staticmethod
    def _scaling_from_config(config: dict) -> dict[str, float]:
        def _safe(key: str) -> float:
            try:
                val = float(config.get(key, 1.0))
            except Exception:
                val = 1.0
            return max(0.0, min(2.0, val))

        return {
            "delay_scale": _safe("delay_scale"),
            "cooldown_scale": _safe("cooldown_scale"),
            "duration_scale": _safe("duration_scale"),
            "strength_scale": _safe("strength_scale"),
        }

    def _command_timeout(self, config: dict) -> float:
        scaling = self._scaling_from_config(config)
        return max(0.0, self._base_command_timeout * scaling["delay_scale"])

    def _cooldown_seconds(self, config: dict) -> float:
        scaling = self._scaling_from_config(config)
        return max(0.0, self._base_cooldown_seconds * scaling["cooldown_scale"])

    def _shock_params(self, config: dict) -> tuple[int, float]:
        scaling = self._scaling_from_config(config)
        strength = int(max(0.0, self._base_shock_strength * scaling["strength_scale"]))
        duration = max(0.0, self._base_shock_duration * scaling["duration_scale"])
        return strength, duration
