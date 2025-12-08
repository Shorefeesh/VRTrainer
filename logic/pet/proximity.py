from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import RemoteServerInterface
from logic.logging_utils import LogFile


class ProximityFeature:
    """Pet proximity feature.

    Evaluates distance to each trainer in the active session using the
    per-trainer config delivered over the server. All logic runs locally
    but settings originate from the assigned trainer profile.
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

        self._state_by_trainer: Dict[str, _TrainerProximityState] = {}

        # Tunables shared by all trainers; per-trainer scaling applied on the fly.
        self._poll_interval: float = 0.1
        self._proximity_threshold: float = 0.4
        self._base_breach_duration: float = 0.5
        self._base_cooldown_seconds: float = 5.0
        self._base_shock_strength_min: float = 20.0
        self._base_shock_strength_max: float = 80.0
        self._base_shock_duration: float = 0.5
        self._base_command_timeout: float = 4.0
        self._command_target: float = 1

        self._log("event=init feature=proximity runtime=pet")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        import threading

        thread = self._thread = threading.Thread(
            target=self._worker_loop,
            name="PetProximityFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=proximity runtime=pet")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=proximity runtime=pet")

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        import time

        while not self._stop_event.is_set():
            now = time.time()
            proximity_value = self.osc.get_float_param("Trainer/Proximity", default=1.0)

            active_configs = self._active_trainer_configs()
            self._prune_inactive_states(active_configs)

            if not active_configs:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            summon_events = self._collect_remote_summons()

            for trainer_id, config in active_configs.items():
                state = self._state_by_trainer.setdefault(trainer_id, _TrainerProximityState())

                if summon_events.get(trainer_id):
                    state.pending_command_from = trainer_id
                    state.pending_command_deadline = now + self._command_timeout(config)
                    self._log(
                        f"event=command_start feature=proximity runtime=pet trainer={trainer_id[:8]} name=summon"
                    )
                    self._send_stats(
                        {
                            "event": "command_start",
                            "runtime": "pet",
                            "feature": "proximity",
                            "name": "summon",
                        },
                        target_client=trainer_id,
                    )

                if state.pending_command_deadline is not None:
                    if self._meets_command_target(proximity_value):
                        state.pending_command_deadline = None
                        trainer_target = state.pending_command_from
                        state.pending_command_from = None
                        self._log(
                            f"event=command_success feature=proximity runtime=pet trainer={trainer_id[:8]} name=summon proximity={proximity_value:.3f}"
                        )
                        self._send_stats(
                            {
                                "event": "command_success",
                                "runtime": "pet",
                                "feature": "proximity",
                                "name": "summon",
                                "proximity": proximity_value,
                            },
                            target_client=trainer_target,
                        )
                    elif now >= state.pending_command_deadline and now >= state.cooldown_until:
                        trainer_target = state.pending_command_from
                        state.pending_command_from = None
                        self._deliver_correction(
                            trainer_id,
                            config,
                            "summon command missed",
                            proximity_value,
                            target_client=trainer_target,
                        )
                        state.cooldown_until = now + self._cooldown_seconds(config)
                        state.pending_command_deadline = None

                if now >= state.cooldown_until and self._is_too_far(now, proximity_value, state, config):
                    self._deliver_correction(
                        trainer_id,
                        config,
                        "too far from trainer",
                        proximity_value,
                        broadcast_trainers=True,
                    )
                    state.cooldown_until = now + self._cooldown_seconds(config)
                    state.breach_started_at = None

                self._log_sample(now, trainer_id, state, proximity_value)

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
        return {tid: cfg for tid, cfg in configs.items() if cfg.get("feature_proximity")}

    def _prune_inactive_states(self, active_configs: Dict[str, dict]) -> None:
        for trainer_id in list(self._state_by_trainer.keys()):
            if trainer_id not in active_configs:
                self._state_by_trainer.pop(trainer_id, None)

    def _is_too_far(self, now: float, proximity_value: float, state: "_TrainerProximityState", config: dict) -> bool:
        if proximity_value >= self._proximity_threshold:
            state.breach_started_at = None
            return False

        if state.breach_started_at is None:
            state.breach_started_at = now
            return False

        return (now - state.breach_started_at) >= self._breach_duration(config)

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
            shock_min, shock_max, shock_duration = self._shock_params(config)
            deficit = (self._proximity_threshold - proximity_value) / self._proximity_threshold
            strength = max(shock_min, min(shock_max, int(deficit * shock_max)))
            self.pishock.send_shock(strength=strength, duration=shock_duration)
            self._log(
                f"event=shock feature=proximity runtime=pet trainer={trainer_id[:8]} reason={reason.replace(' ', '_')} proximity={proximity_value:.3f} threshold={self._proximity_threshold:.3f} strength={strength}"
            )
            self._send_stats(
                {
                    "event": "shock",
                    "runtime": "pet",
                    "feature": "proximity",
                    "reason": reason,
                    "proximity": proximity_value,
                    "threshold": self._proximity_threshold,
                    "strength": strength,
                },
                target_client=target_client or trainer_id,
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

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return

    def _log_sample(self, now: float, trainer_id: str, state: "_TrainerProximityState", proximity_value: float) -> None:
        if now - state.last_sample_log < 1.0:
            return

        state.last_sample_log = now
        self._log(
            f"event=sample feature=proximity runtime=pet trainer={trainer_id[:8]} value={proximity_value:.3f} threshold={self._proximity_threshold:.3f}"
        )
        self._send_stats(
            {
                "event": "sample",
                "runtime": "pet",
                "feature": "proximity",
                "value": proximity_value,
                "threshold": self._proximity_threshold,
            },
            target_client=trainer_id,
        )

    def _send_stats(self, stats: dict[str, object], *, target_client: str | None = None, broadcast_trainers: bool | None = None) -> None:
        server = self.server
        if server is None:
            return

        try:
            server.send_logs(stats, target_clients=[target_client] if target_client else None, broadcast_trainers=broadcast_trainers)
        except Exception:
            return

    def _shock_params(self, config: dict) -> tuple[float, float, float]:
        scaling = self._scaling_from_config(config)
        shock_min = max(0.0, self._base_shock_strength_min * scaling["strength_scale"])
        shock_max = max(shock_min, self._base_shock_strength_max * scaling["strength_scale"])
        shock_duration = max(0.0, self._base_shock_duration * scaling["duration_scale"])
        return shock_min, shock_max, shock_duration

    def _cooldown_seconds(self, config: dict) -> float:
        scaling = self._scaling_from_config(config)
        return max(0.0, self._base_cooldown_seconds * scaling["cooldown_scale"])

    def _command_timeout(self, config: dict) -> float:
        scaling = self._scaling_from_config(config)
        return max(0.0, self._base_command_timeout * scaling["delay_scale"])

    def _breach_duration(self, config: dict) -> float:
        scaling = self._scaling_from_config(config)
        return max(0.0, self._base_breach_duration * scaling["delay_scale"])

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


@dataclass
class _TrainerProximityState:
    breach_started_at: float | None = None
    cooldown_until: float = 0.0
    pending_command_deadline: float | None = None
    pending_command_from: str | None = None
    last_sample_log: float = field(default_factory=lambda: 0.0)
