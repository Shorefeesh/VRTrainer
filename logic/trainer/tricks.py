from __future__ import annotations

import threading
from typing import Callable, Dict

from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import RemoteServerInterface
from interfaces.whisper import WhisperInterface
from logic.logging_utils import LogFile


class TrainerTricksFeature:
    """Trainer-side whisper listener for trick commands."""

    def __init__(
        self,
        whisper: WhisperInterface,
        server: RemoteServerInterface,
        osc: VRChatOSCInterface | None = None,
        *,
        names: list[str] | None = None,
        config_provider: Callable[[], Dict[str, dict]] | None = None,
        logger: LogFile | None = None,
    ) -> None:
        self.whisper = whisper
        self.server = server
        self.osc = osc
        self._logger = logger
        self._enabled = True
        self._running = False

        self._whisper_tag = "trainer_tricks_feature"
        self._config_provider = config_provider
        self._default_pet_names = [self._normalise_text(name) for name in (names or []) if self._normalise_text(name)]

        self._poll_interval: float = 0.2
        self._command_phrases: dict[str, list[str]] = {
            "paw": ["paw", "poor", "pour", "pore"],
            "sit": ["sit"],
            "lay_down": ["lay down", "laydown", "lie down", "layed down"],
            "beg": ["beg"],
            "play_dead": ["play dead", "playdead", "played dead"],
            "roll_over": ["rollover", "roll over"],
        }

        self._command_ids: dict[str, int] = {
            "paw": 1,
            "sit": 2,
            "lay_down": 3,
            "beg": 4,
            "play_dead": 5,
            "roll_over": 6,
        }

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        try:
            self.whisper.reset_tag(self._whisper_tag)
        except Exception:
            pass

        thread = self._thread = threading.Thread(
            target=self._worker_loop,
            name="TrainerTricksFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=tricks runtime=trainer")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=tricks runtime=trainer")

    # Internal helpers -------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled and not self._enabled:
            # Discard any queued transcript so we only react to speech
            # that happens after the feature is enabled.
            try:
                self.whisper.reset_tag(self._whisper_tag)
            except Exception:
                pass
        self._enabled = enabled

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._enabled:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            try:
                text = self.whisper.get_new_text(self._whisper_tag)
            except Exception:
                text = ""

            pet_configs = self._iter_pet_configs()
            if pet_configs and text:
                first_sent: str | None = None
                for pet_id, cfg in pet_configs.items():
                    if not str(pet_id):
                        continue
                    if not cfg.get("feature_tricks"):
                        continue

                    pet_names = self._extract_names(cfg)
                    detected = self._detect_command(text, pet_names)
                    if detected is None:
                        continue

                    meta = {"feature": "tricks", "target_client": str(pet_id)}
                    try:
                        self.server.send_command(detected, meta)
                        self._log(
                            f"event=command_start feature=tricks runtime=trainer pet={str(pet_id)[:8]} name={detected}"
                        )
                        if first_sent is None:
                            first_sent = detected
                    except Exception:
                        continue

                if first_sent is not None:
                    self._pulse_command(first_sent)

            if self._stop_event.wait(self._poll_interval):
                break

    def _iter_pet_configs(self) -> Dict[str, dict]:
        provider = self._config_provider
        if provider is None:
            return {}

        try:
            configs = provider() or {}
            return {pid: cfg for pid, cfg in configs.items() if isinstance(cfg, dict)}
        except Exception:
            return {}

    def _extract_names(self, config: dict) -> list[str]:
        names = config.get("names") if isinstance(config, dict) else None
        pet_names = [self._normalise_text(n) for n in (names or []) if self._normalise_text(n)]
        if not pet_names:
            pet_names = list(self._default_pet_names)
        return pet_names

    def _detect_command(self, text: str, pet_names: list[str]) -> str | None:
        if not text:
            return None

        normalised = self._normalise_text(text)
        if not normalised:
            return None

        if pet_names:
            recent_chunks = self.whisper.get_recent_text_chunks(count=3)
            recent_normalised = " ".join(self._normalise_text(chunk) for chunk in recent_chunks if chunk)
            if not any(name in recent_normalised for name in pet_names):
                return None

        for cmd, phrases in self._command_phrases.items():
            for phrase in phrases:
                if phrase and phrase in normalised:
                    return cmd
        return None

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

    def _pulse_command(self, command: str) -> None:
        osc = self.osc
        if osc is None:
            return

        try:
            cmd_id = self._command_ids.get(command, 0)
            if cmd_id:
                osc.send_parameter("Trainer/CommandTrickId", cmd_id)
            osc.pulse_parameter("Trainer/CommandTrick", value_on=1, value_off=0, duration=0.2)
        except Exception:
            return
