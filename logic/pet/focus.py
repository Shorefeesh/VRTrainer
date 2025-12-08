from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, List

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import RemoteServerInterface
from logic.logging_utils import LogFile


class FocusFeature:
    """Pet focus feature.

    Runs on the pet client, reading OSC eye-contact parameters and
    delivering shocks locally when focus drops too low.
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

        self._state_by_trainer: Dict[str, _TrainerFocusState] = {}

        # Focus meter state and tunables.
        self._poll_interval: float = 0.1
        self._fill_rate: float = 0.2
        self._drain_rate: float = 0.02
        self._shock_threshold: float = 0.2

        self._base_cooldown_seconds: float = 5.0

        self._base_shock_strength_min: float = 20.0
        self._base_shock_strength_max: float = 80.0
        self._base_shock_duration: float = 0.5
        self._name_penalty: float = 0.15

        self._log("event=init feature=focus runtime=pet")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        import threading

        thread = self._thread = threading.Thread(
            target=self._worker_loop,
            name="PetFocusFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=focus runtime=pet")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=focus runtime=pet")

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        import time

        while not self._stop_event.is_set():
            now = time.time()

            active_configs = self._active_trainer_configs()
            self._prune_inactive_states(active_configs)

            if not active_configs:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            penalties = self._collect_focus_events()

            for trainer_id, config in active_configs.items():
                state = self._state_by_trainer.setdefault(trainer_id, _TrainerFocusState(now))
                dt = max(0.0, now - state.last_tick)
                state.last_tick = now

                self._apply_remote_penalties_for_trainer(trainer_id, state, penalties.get(trainer_id, []))
                self._update_meter(state, dt)
                self._log_sample(now, trainer_id, state)

                if self._should_shock(now, state):
                    self._deliver_correction(trainer_id, state, config)
                    state.cooldown_until = now + self._cooldown_seconds(config)

            if self._stop_event.wait(self._poll_interval):
                break

    def _active_trainer_configs(self) -> Dict[str, dict]:
        server = self.server
        if server is None:
            return {}

        configs = getattr(server, "latest_settings_by_trainer", lambda: {})()
        return {tid: cfg for tid, cfg in configs.items() if cfg.get("feature_focus")}

    def _prune_inactive_states(self, active_configs: Dict[str, dict]) -> None:
        for trainer_id in list(self._state_by_trainer.keys()):
            if trainer_id not in active_configs:
                self._state_by_trainer.pop(trainer_id, None)

    def _collect_focus_events(self) -> Dict[str, List[dict]]:
        if self.server is None:
            return {}

        events = self.server.poll_events(
            limit=10,
            predicate=lambda evt: (
                isinstance(evt, dict)
                and isinstance(evt.get("payload"), dict)
                and evt.get("payload", {}).get("type") == "command"
                and evt.get("payload", {}).get("meta", {}).get("feature") == "focus"
            ),
        )

        grouped: Dict[str, List[dict]] = {}
        for event in events:
            trainer_id = str(event.get("from_client") or "")
            if trainer_id:
                grouped.setdefault(trainer_id, []).append(event)
        return grouped

    def _update_meter(self, state: "_TrainerFocusState", dt: float) -> None:
        focused = self.osc.get_bool_param("Trainer/Focus", default=True)
        delta = (self._fill_rate if focused else -self._drain_rate) * dt
        state.focus_meter = max(0.0, min(1.0, state.focus_meter + delta))

    def _apply_remote_penalties_for_trainer(self, trainer_id: str, state: "_TrainerFocusState", events: List[dict]) -> None:
        if not events:
            return

        state.last_command_trainer = trainer_id or state.last_command_trainer
        for _event in events:
            state.focus_meter = max(0.0, state.focus_meter - self._name_penalty)

    def _should_shock(self, now: float, state: "_TrainerFocusState") -> bool:
        if now < state.cooldown_until:
            return False
        return state.focus_meter <= self._shock_threshold

    def _deliver_correction(self, trainer_id: str, state: "_TrainerFocusState", config: dict) -> None:
        try:
            shock_min, shock_max, shock_duration = self._shock_params(config)
            deficit = (self._shock_threshold - state.focus_meter) / self._shock_threshold
            strength = max(shock_min, min(shock_max, int(deficit * shock_max)))
            self.pishock.send_shock(strength=strength, duration=shock_duration)
            self._log(
                f"event=shock feature=focus runtime=pet trainer={trainer_id[:8]} meter={state.focus_meter:.3f} threshold={self._shock_threshold:.3f} strength={strength}"
            )
            self._send_stats(
                {
                    "event": "shock",
                    "runtime": "pet",
                    "feature": "focus",
                    "meter": state.focus_meter,
                    "threshold": self._shock_threshold,
                    "strength": strength,
                },
                target_client=trainer_id,
            )
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

    def _log_sample(self, now: float, trainer_id: str, state: "_TrainerFocusState") -> None:
        if now - state.last_sample_log < 1.0:
            return

        state.last_sample_log = now
        self._log(
            f"event=sample feature=focus runtime=pet trainer={trainer_id[:8]} meter={state.focus_meter:.3f} threshold={self._shock_threshold:.3f}"
        )
        self._send_stats(
            {
                "event": "sample",
                "runtime": "pet",
                "feature": "focus",
                "meter": state.focus_meter,
                "threshold": self._shock_threshold,
            },
            target_client=trainer_id,
        )

    @staticmethod
    def _normalise(text: str) -> str:
        if not text:
            return ""

        chars: list[str] = []
        for ch in text.lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch.isspace():
                chars.append(" ")
            else:
                chars.append(" ")

        return " ".join("".join(chars).split())

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
class _TrainerFocusState:
    last_tick: float = field(default_factory=lambda: 0.0)
    focus_meter: float = 1.0
    cooldown_until: float = 0.0
    last_sample_log: float = 0.0
    last_command_trainer: str | None = None
