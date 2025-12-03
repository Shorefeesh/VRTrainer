from __future__ import annotations

import threading
import time
from typing import Iterable, List, Optional

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface


class ScoldingFeature:
    """Trainer scolding feature.

    Detects scolding words spoken by the trainer via Whisper and uses
    PiShock to deliver feedback.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        whisper: WhisperInterface,
        *,
        scolding_words: Optional[Iterable[str]] = None,
        difficulty: Optional[str] = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self._running = False
        self._enabled = True

        # Background worker thread that consumes Whisper transcripts.
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Tag used when reading from Whisper so this feature has an
        # independent view of the transcript.
        self._whisper_tag = "trainer_scolding_feature"

        # Preprocess scolding phrases for case-insensitive, punctuation-
        # insensitive matching.
        self._scolding_phrases: List[str] = self._normalise_phrases(scolding_words or [])

        # Cooldown between shocks so a long sentence containing
        # multiple scolding phrases does not spam PiShock.
        self._cooldown_seconds: float = 3.0
        self._cooldown_until: float = 0.0

        # Shock strength can be tuned by difficulty.
        self._shock_strength: int = 30
        self._apply_difficulty(difficulty)

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        # Ensure we only see future transcript text.
        try:
            self.whisper.reset_tag(self._whisper_tag)
        except Exception:
            # If Whisper is not fully initialised, continue anyway; the
            # worker loop will simply see empty text.
            pass

        thread = threading.Thread(
            target=self._worker_loop,
            name="TrainerScoldingFeature",
            daemon=True,
        )
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

    # Internal helpers -------------------------------------------------
    def _apply_difficulty(self, difficulty: Optional[str]) -> None:
        """Configure shock strength/cooldown based on difficulty label."""
        level = (difficulty or "Normal").strip().lower()
        if level == "easy":
            self._shock_strength = 20
            self._cooldown_seconds = 5.0
        elif level == "hard":
            self._shock_strength = 40
            self._cooldown_seconds = 2.0

    def _worker_loop(self) -> None:
        """Background loop that watches Whisper transcripts."""
        while not self._stop_event.is_set():
            if not self._enabled:
                if self._stop_event.wait(0.5):
                    break
                continue

            try:
                text = self.whisper.get_new_text(self._whisper_tag)
            except Exception:
                text = ""

            if text and self._scolding_phrases:
                if self._contains_scolding(text):
                    now = time.time()
                    if now >= self._cooldown_until:
                        self._deliver_scolding_shock()
                        self._cooldown_until = now + self._cooldown_seconds

            # Sleep briefly to limit CPU usage while still reacting
            # quickly to new speech.
            if self._stop_event.wait(0.5):
                break

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable scolding detection."""

        self._enabled = bool(enabled)

    def _contains_scolding(self, text: str) -> bool:
        """Return True if the text includes any configured scolding phrase."""
        if not text:
            return False

        normalised = self._normalise(text)
        if not normalised:
            return False

        for phrase in self._scolding_phrases:
            if phrase and phrase in normalised:
                return True
        return False

    def _normalise_phrases(self, words: Iterable[str]) -> List[str]:
        """Normalise configured phrases for matching."""
        return [self._normalise(word) for word in words if word and self._normalise(word)]

    @staticmethod
    def _normalise(text: str) -> str:
        """Normalise text for case- and punctuation-insensitive search."""
        if not text:
            return ""

        chars: List[str] = []
        for ch in text.lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch.isspace():
                chars.append(" ")
            else:
                # Replace punctuation with spaces so multi-word phrases
                # like "bad fox!" still match "Bad fox".
                chars.append(" ")

        cleaned = "".join(chars)
        # Collapse multiple whitespace into single spaces and trim.
        return " ".join(cleaned.split())

    def _deliver_scolding_shock(self) -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            self.pishock.send_shock(strength=self._shock_strength, duration=0.5)
        except Exception:
            # Never let PiShock errors break the feature loop.
            return
