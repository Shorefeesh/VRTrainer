from __future__ import annotations

import threading

from interfaces.server import DummyServerInterface
from interfaces.whisper import WhisperInterface
from logic.logging_utils import LogFile


class TrainerFocusFeature:
    """Trainer-side listener that relays focus-related voice cues."""

    def __init__(
        self,
        whisper: WhisperInterface,
        server: DummyServerInterface,
        *,
        names: list[str] | None = None,
        logger: LogFile | None = None,
    ) -> None:
        self.whisper = whisper
        self.server = server
        self._logger = logger
        self._enabled = True
        self._running = False

        self._whisper_tag: str = "trainer_focus_feature"
        self._pet_names: list[str] = [self._normalise(name) for name in (names or []) if self._normalise(name)]
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
            name="TrainerFocusFeature",
            daemon=True,
        )
        thread.start()

        self._log("event=start feature=focus runtime=trainer")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=focus runtime=trainer")

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

            if text:
                self._maybe_send_focus_command(text)

            if self._stop_event.wait(self._poll_interval):
                break

    def _maybe_send_focus_command(self, text: str) -> None:
        normalised = self._normalise(text)
        if not normalised:
            return

        penalties: list[str] = []
        if self._pet_names and any(name in normalised for name in self._pet_names):
            penalties.append("name")

        command_words = self._get_command_phrases()
        if any(cmd in normalised for cmd in command_words):
            penalties.append("command_word")

        if not penalties:
            return

        try:
            self.server.send_command("focus", {"feature": "focus", "reasons": penalties, "text": normalised})
            self._log(
                f"event=command_start feature=focus runtime=trainer reasons={'|'.join(penalties)} text={normalised}"
            )
        except Exception:
            pass

    def _get_command_phrases(self) -> list[str]:
        raw = []
        try:
            raw = self.server.get_setting("command_words", []) or []
        except Exception:
            raw = []

        phrases = [self._normalise(word) for word in raw if self._normalise(word)]
        if not phrases:
            phrases = [self._normalise(word) for word in self._default_command_phrases]
        return phrases

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

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return
