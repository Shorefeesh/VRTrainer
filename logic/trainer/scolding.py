from __future__ import annotations

import threading

from interfaces.server import DummyServerInterface
from interfaces.whisper import WhisperInterface
from logic.logging_utils import LogFile


class TrainerScoldingFeature:
    """Trainer-side listener that forwards scolding words to the server."""

    def __init__(
        self,
        whisper: WhisperInterface,
        server: DummyServerInterface,
        *,
        scolding_words: list[str] | None = None,
        logger: LogFile | None = None,
    ) -> None:
        self.whisper = whisper
        self.server = server
        self._logger = logger
        self._enabled = True
        self._running = False

        self._whisper_tag = "trainer_scolding_feature"
        self._scolding_phrases = [self._normalise(word) for word in (scolding_words or []) if self._normalise(word)]
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
                self._maybe_send_scold(text)

            if self._stop_event.wait(self._poll_interval):
                break

    def _maybe_send_scold(self, text: str) -> None:
        normalised = self._normalise(text)
        if not normalised:
            return

        phrases = self._get_scolding_phrases()
        if not phrases:
            return

        if any(phrase in normalised for phrase in phrases):
            try:
                self.server.send_scold(normalised, {"feature": "scolding"})
                self._log("event=scold feature=scolding runtime=trainer text=" + normalised)
            except Exception:
                pass

    def _get_scolding_phrases(self) -> list[str]:
        if self._scolding_phrases:
            return self._scolding_phrases

        raw: list[str] = []
        try:
            raw = self.server.get_setting("scolding_words", []) or []
        except Exception:
            raw = []

        return [self._normalise(word) for word in raw if self._normalise(word)]

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
