from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List

from interfaces.pishock import PiShockInterface
from interfaces.server import RemoteServerInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface
from logic.logging_utils import LogFile


@dataclass
class _TrainerForbiddenState:
    cooldown_until: float = 0.0


class ForbiddenWordsFeature:
    """Pet forbidden-words feature.

    Listens to pet speech via Whisper and applies corrections when any trainer
    configured forbidden word is spoken. Word lists are pulled from *all*
    trainers currently in the session so multiple trainers can contribute their
    own rules simultaneously.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        whisper: WhisperInterface,
        server: RemoteServerInterface | None = None,
        logger: LogFile | None = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self.server = server
        self._logger = logger
        self._running = False
        self._active = False

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._whisper_tag = "pet_forbidden_words_feature"

        self._state_by_trainer: Dict[str, _TrainerForbiddenState] = {}
        self._phrases_by_trainer: Dict[str, List[str]] = {}

        self._poll_interval: float = 0.4
        self._base_cooldown_seconds: float = 3.0
        self._base_shock_strength: float = 30
        self._base_shock_duration: float = 0.5

        self._log("event=init feature=forbidden_words runtime=pet")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        try:
            self.whisper.reset_tag(self._whisper_tag)
        except Exception:
            pass

        thread = threading.Thread(
            target=self._worker_loop,
            name="PetForbiddenWordsFeature",
            daemon=True,
        )
        self._thread = thread
        thread.start()

        self._log("event=start feature=forbidden_words runtime=pet")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=forbidden_words runtime=pet")

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            active_configs = self._active_trainer_configs()
            self._prune_inactive_states(active_configs)

            now_active = bool(active_configs)
            if now_active and not self._active:
                # Feature just became active; discard any buffered speech.
                try:
                    self.whisper.reset_tag(self._whisper_tag)
                except Exception:
                    pass
            self._active = now_active

            if not active_configs:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            text = self._get_new_text()
            normalised_text = self._normalise(text)

            if not normalised_text:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            now = time.time()
            shock_sent = False
            for trainer_id, config in active_configs.items():
                state = self._state_by_trainer.setdefault(trainer_id, _TrainerForbiddenState())
                phrases = self._update_phrases(trainer_id, config)

                if not phrases:
                    continue

                if now < state.cooldown_until:
                    continue

                if self._contains_forbidden(normalised_text, phrases):
                    self._deliver_correction(trainer_id, config)
                    state.cooldown_until = now + self._cooldown_seconds(config)
                    shock_sent = True

                if shock_sent:
                    break

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
        return {tid: cfg for tid, cfg in configs.items() if cfg.get("feature_forbidden_words")}

    def _prune_inactive_states(self, active_configs: Dict[str, dict]) -> None:
        for trainer_id in list(self._state_by_trainer.keys()):
            if trainer_id not in active_configs:
                self._state_by_trainer.pop(trainer_id, None)
                self._phrases_by_trainer.pop(trainer_id, None)

    def _get_new_text(self) -> str:
        try:
            return self.whisper.get_new_text(self._whisper_tag)
        except Exception:
            return ""

    def _update_phrases(self, trainer_id: str, config: dict) -> List[str]:
        phrases = self._normalise_phrases(config.get("forbidden_words", []))
        self._phrases_by_trainer[trainer_id] = phrases
        return phrases

    def _normalise_phrases(self, words: Iterable[str]) -> List[str]:
        return [self._normalise(word) for word in words if word and self._normalise(word)]

    @staticmethod
    def _normalise(text: str | None) -> str:
        if not text:
            return ""

        chars: List[str] = []
        for ch in text.lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch.isspace():
                chars.append(" ")
            else:
                chars.append(" ")

        cleaned = "".join(chars)
        return " ".join(cleaned.split())

    def _contains_forbidden(self, normalised_text: str, phrases: List[str]) -> bool:
        for phrase in phrases:
            if phrase and phrase in normalised_text:
                return True
        return False

    def _deliver_correction(self, trainer_id: str, config: dict) -> None:
        try:
            strength, duration = self._shock_params(config)
            self.pishock.send_shock(strength=strength, duration=duration)
            self._log(
                f"event=shock feature=forbidden_words runtime=pet trainer={trainer_id[:8]} strength={strength}"
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
