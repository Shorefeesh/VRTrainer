from __future__ import annotations

import threading
from typing import Callable, Dict

from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import RemoteServerInterface
from interfaces.whisper import WhisperInterface
from logic.logging_utils import LogFile


class TrainerScoldingFeature:
    """Trainer-side listener that forwards scolding words to the server."""

    def __init__(
        self,
        whisper: WhisperInterface,
        server: RemoteServerInterface,
        osc: VRChatOSCInterface | None = None,
        *,
        scolding_words: list[str] | None = None,
        config_provider: Callable[[], Dict[str, dict]] | None = None,
        logger: LogFile | None = None,
    ) -> None:
        self.whisper = whisper
        self.server = server
        self.osc = osc
        self._logger = logger
        self._enabled = True
        self._running = False

        self._whisper_tag = "trainer_scolding_feature"
        self._config_provider = config_provider
        self._scolding_phrases = self._normalise_list(scolding_words)
        self._poll_interval = 0.2

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
            name="TrainerScoldingFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=scolding runtime=trainer")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=scolding runtime=trainer")

    # Internal helpers -------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled and not self._enabled:
            # Flush old transcript entries so only fresh speech is considered.
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

            if text:
                self._maybe_send_scold(text)

            if self._stop_event.wait(self._poll_interval):
                break

    def set_scolding_words(self, scolding_words: list[str] | None) -> None:
        """Update the scolding word list while running."""
        self._scolding_phrases = self._normalise_list(scolding_words)
        # Reset transcript so new phrases only match fresh speech.
        try:
            self.whisper.reset_tag(self._whisper_tag)
        except Exception:
            pass

    def _maybe_send_scold(self, text: str) -> None:
        normalised = self._normalise(text)
        if not normalised:
            return

        pet_configs = self._iter_pet_configs()
        if not pet_configs:
            return

        for pet_id, cfg in pet_configs.items():
            if not str(pet_id):
                continue
            if not cfg.get("feature_scolding"):
                continue

            phrases = self._get_scolding_phrases(cfg)
            if not phrases:
                continue

            if any(phrase in normalised for phrase in phrases):
                meta = {"feature": "scolding", "target_client": str(pet_id)}
                try:
                    self.server.send_command(normalised, meta)
                    self._log(
                        "event=scold feature=scolding runtime=trainer pet="
                        + str(pet_id)[:8]
                        + " text="
                        + normalised
                    )
                    self._pulse_command_flag("Trainer/CommandScold")
                except Exception:
                    continue

    def _get_scolding_phrases(self, config: dict | None) -> list[str]:
        if self._scolding_phrases:
            return self._scolding_phrases

        raw: list[str] = []
        try:
            if isinstance(config, dict):
                raw = config.get("scolding_words", []) or []
            else:
                raw = self.server.get_setting("scolding_words", []) or []
        except Exception:
            raw = []

        return self._normalise_list(raw)

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

    def _normalise_list(self, words: list[str] | None) -> list[str]:
        return [self._normalise(word) for word in (words or []) if self._normalise(word)]

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return

    def _pulse_command_flag(self, flag_name: str) -> None:
        osc = self.osc
        if osc is None:
            return

        try:
            osc.pulse_parameter(flag_name, value_on=1, value_off=0, duration=0.2)
        except Exception:
            return

    # Config helpers -------------------------------------------------
    def _iter_pet_configs(self) -> Dict[str, dict]:
        provider = self._config_provider
        if provider is None:
            return {}

        try:
            configs = provider() or {}
            return {pid: cfg for pid, cfg in configs.items() if isinstance(cfg, dict)}
        except Exception:
            return {}
