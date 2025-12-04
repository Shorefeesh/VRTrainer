from __future__ import annotations

import threading

from interfaces.server import DummyServerInterface
from interfaces.whisper import WhisperInterface
from logic.logging_utils import LogFile


class TrainerTricksFeature:
    """Trainer-side whisper listener for trick commands."""

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

        self._whisper_tag = "trainer_tricks_feature"
        self._pet_names = [self._normalise_text(name) for name in (names or []) if self._normalise_text(name)]

        self._poll_interval: float = 0.2
        self._command_phrases: dict[str, list[str]] = {
            "paw": ["paw", "poor", "pour", "pore"],
            "sit": ["sit"],
            "lay_down": ["lay down", "laydown", "lie down", "layed down"],
            "beg": ["beg"],
            "play_dead": ["play dead", "playdead", "played dead"],
            "roll_over": ["rollover", "roll over"],
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

            detected = self._detect_command(text)
            if detected is not None:
                try:
                    self.server.send_command(detected, {"feature": "tricks"})
                    self._log(f"event=command_start feature=tricks runtime=trainer name={detected}")
                except Exception:
                    pass

            if self._stop_event.wait(self._poll_interval):
                break

    def _detect_command(self, text: str) -> str | None:
        if not text:
            return None

        normalised = self._normalise_text(text)
        if not normalised:
            return None

        if self._pet_names:
            recent_chunks = self.whisper.get_recent_text_chunks(count=3)
            recent_normalised = " ".join(self._normalise_text(chunk) for chunk in recent_chunks if chunk)
            if not any(name in recent_normalised for name in self._pet_names):
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
