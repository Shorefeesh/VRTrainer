from __future__ import annotations

import threading
import time
from typing import Optional, Set

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface
from logic.logging_utils import LogFile


class PronounsFeature:
    """Pet pronouns feature.

    Listens to first-person speech from the pet via Whisper and uses
    PiShock to reinforce preferred pronoun usage.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        whisper: WhisperInterface,
        logger: LogFile | None = None,
    ) -> None:
        # Interfaces are provided for future expansion; OSC is not
        # currently used by this feature but is kept for parity with
        # other features.
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self._running = False
        self._enabled = True
        self._logger = logger

        # Background worker thread that consumes Whisper transcripts.
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Tag used when reading from Whisper so this feature has an
        # independent view of the transcript.
        self._whisper_tag = "pet_pronouns_feature"

        # Simple cooldown to avoid spamming shocks if the pet speaks
        # in long sentences or Whisper groups multiple pronouns into
        # one chunk.
        self._cooldown_seconds = 5.0
        self._cooldown_until: float = 0.0
        self._shock_strength: float = 20.0

        # Disallowed first-person pronoun tokens. Tokens are compared
        # in a case-insensitive, punctuation-stripped fashion.
        self._disallowed_tokens: Set[str] = {
            "i",
            "im",
            "i'm",
            "ive",
            "i've",
            "ill",
            "i'll",
            "me",
            "my",
            "mine",
            "myself",
        }

        self._log("event=init feature=pronouns")

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
            name="PetPronounsFeature",
            daemon=True,
        )
        self._thread = thread
        thread.start()

        self._log("event=start feature=pronouns")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=pronouns")

    # Internal helpers -------------------------------------------------
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

            if text:
                if self._contains_disallowed_pronouns(text):
                    now = time.time()
                    if now >= self._cooldown_until:
                        self._deliver_correction()
                        self._cooldown_until = now + self._cooldown_seconds

            # Sleep briefly to limit CPU usage while still reacting
            # quickly to new speech.
            if self._stop_event.wait(0.5):
                break

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable pronoun monitoring."""

        self._enabled = bool(enabled)

    def _contains_disallowed_pronouns(self, text: str) -> bool:
        """Return True if the text includes first-person pronouns."""
        if not text:
            return False

        for raw_token in text.split():
            # Strip common punctuation while keeping letters and
            # apostrophes so "I'm" and "I'll" can be matched.
            cleaned = "".join(ch for ch in raw_token if ch.isalpha() or ch in ("'", "’")).lower()
            if not cleaned:
                continue

            # Check both with and without apostrophes to cover variants
            # like "I'm" vs "Im".
            if cleaned in self._disallowed_tokens:
                return True

            no_apostrophe = cleaned.replace("'", "").replace("’", "")
            if no_apostrophe and no_apostrophe in self._disallowed_tokens:
                return True

        return False

    def _deliver_correction(self) -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            # Use a modest default intensity and short pulse so that
            # this feature is usable out of the box without further
            # tuning. Values can be adjusted later or made configurable.
            self.pishock.send_shock(strength=self._shock_strength, duration=0.5)
            self._log(f"event=shock feature=pronouns strength={self._shock_strength}")
        except Exception:
            # Never let PiShock errors break the feature loop.
            return

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return
