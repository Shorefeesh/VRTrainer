from __future__ import annotations

import threading

from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.server import RemoteServerInterface
from interfaces.whisper import WhisperInterface
from logic.logging_utils import LogFile


class TrainerProximityFeature:
    """Trainer-side whisper listener for proximity (summon) commands."""

    def __init__(
        self,
        whisper: WhisperInterface,
        server: RemoteServerInterface,
        osc: VRChatOSCInterface | None = None,
        *,
        names: list[str] | None = None,
        logger: LogFile | None = None,
    ) -> None:
        self.whisper = whisper
        self.server = server
        self.osc = osc
        self._logger = logger
        self._enabled = True
        self._running = False

        self._whisper_tag = "trainer_proximity_feature"
        self._pet_names = [self._normalise_text(name) for name in (names or []) if self._normalise_text(name)]
        self._default_command_phrases: list[str] = ["come here", "heel"]

        self._poll_interval: float = 0.1

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
            name="TrainerProximityFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=proximity runtime=trainer")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=proximity runtime=trainer")

    # Internal helpers -------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

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

            if text and self._detect_summon_command(text):
                try:
                    self.server.send_command("summon", {"feature": "proximity"})
                    self._log("event=command_start feature=proximity runtime=trainer name=summon")
                    self._pulse_command_flag("Trainer/CommandSummon")
                except Exception:
                    pass

            if self._stop_event.wait(self._poll_interval):
                break

    def _detect_summon_command(self, text: str) -> bool:
        normalised = self._normalise_text(text)
        if not normalised:
            return False

        command_phrases = self._get_command_phrases()
        if self._pet_names:
            recent_chunks = self.whisper.get_recent_text_chunks(count=3)
            recent_normalised = " ".join(self._normalise_text(chunk) for chunk in recent_chunks if chunk)
            if not any(name in recent_normalised for name in self._pet_names):
                return False

        return any(phrase in normalised for phrase in command_phrases)

    def _get_command_phrases(self) -> list[str]:
        raw: list[str] = []
        try:
            raw = self.server.get_setting("command_words", []) or []
        except Exception:
            raw = []

        phrases = [self._normalise_text(word) for word in raw if self._normalise_text(word)]
        if not phrases:
            phrases = [self._normalise_text(word) for word in self._default_command_phrases]
        return phrases

    @staticmethod
    def _normalise_text(text: str) -> str:
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
