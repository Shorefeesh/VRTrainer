from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from interfaces.pishock import PiShockInterface
from interfaces.server import RemoteServerInterface
from interfaces.vrchatosc import VRChatOSCInterface
from logic.logging_utils import LogFile


@dataclass
class _TrainerScoldState:
    cooldown_until: float = 0.0


class ScoldingFeature:
    """Pet scolding feature.

    Listens for scolding commands from each trainer in the session.
    Config for the trainer (word lists, scaling) is supplied via the
    server; the pet only applies what it receives over the network.
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

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._state_by_trainer: Dict[str, _TrainerScoldState] = {}
        self._phrases_by_trainer: Dict[str, List[str]] = {}

        self._base_cooldown_seconds: float = 3.0
        self._base_shock_strength: float = 30
        self._base_shock_duration: float = 0.5

        self._log("event=init feature=scolding runtime=pet")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        thread = threading.Thread(
            target=self._worker_loop,
            name="PetScoldingFeature",
            daemon=True,
        )
        self._thread = thread
        thread.start()

        self._log("event=start feature=scolding runtime=pet")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=scolding runtime=pet")

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            active_configs = self._active_trainer_configs()
            self._prune_inactive_states(active_configs)

            if not active_configs:
                if self._stop_event.wait(0.5):
                    break
                continue

            events_by_trainer = self._collect_scold_events()
            now = time.time()

            for trainer_id, config in active_configs.items():
                state = self._state_by_trainer.setdefault(trainer_id, _TrainerScoldState())

                if events_by_trainer.get(trainer_id):
                    if now >= state.cooldown_until:
                        self._deliver_scolding_shock(trainer_id, config)
                        state.cooldown_until = now + self._cooldown_seconds(config)

            if self._stop_event.wait(0.5):
                break

    def _active_trainer_configs(self) -> Dict[str, dict]:
        server = self.server
        if server is None:
            return {}
        raw_configs = getattr(server, "latest_settings_by_trainer", None)
        configs = raw_configs() if callable(raw_configs) else raw_configs
        if not isinstance(configs, dict):
            configs = {}
        return {tid: cfg for tid, cfg in configs.items() if cfg.get("feature_scolding")}

    def _prune_inactive_states(self, active_configs: Dict[str, dict]) -> None:
        for trainer_id in list(self._state_by_trainer.keys()):
            if trainer_id not in active_configs:
                self._state_by_trainer.pop(trainer_id, None)
                self._phrases_by_trainer.pop(trainer_id, None)

    def _collect_scold_events(self) -> Dict[str, List[dict]]:
        if self.server is None:
            return {}

        events = self.server.poll_feature_events("scolding", limit=10)

        grouped: Dict[str, List[dict]] = {}
        for event in events:
            trainer_id = str(event.get("from_client") or "")
            if trainer_id:
                grouped.setdefault(trainer_id, []).append(event)
        return grouped

    def _deliver_scolding_shock(self, trainer_id: str, config: dict) -> None:
        try:
            strength, duration = self._shock_params(config)
            self.pishock.send_shock(strength=strength, duration=duration)
            self._log(f"event=shock feature=scolding runtime=pet trainer={trainer_id[:8]} strength={strength}")
        except Exception:
            return

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return

    def _shock_params(self, config: dict) -> tuple[int, float]:
        scaling = self._scaling_from_config(config)
        strength = int(max(0.0, self._base_shock_strength * scaling["strength_scale"]))
        duration = max(0.0, self._base_shock_duration * scaling["duration_scale"])
        return strength, duration

    def _cooldown_seconds(self, config: dict) -> float:
        scaling = self._scaling_from_config(config)
        return max(0.0, self._base_cooldown_seconds * scaling["cooldown_scale"])

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
