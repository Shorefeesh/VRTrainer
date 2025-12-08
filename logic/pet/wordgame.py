from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional, Set

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface
from interfaces.server import RemoteServerInterface
from logic.logging_utils import LogFile


class WordFeature:
    """Pet word feature.

    Listens to pet speech via Whisper and runs the selected "word game".
    Each word game can apply its own rules; currently only the Pronouns
    game is implemented.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        whisper: WhisperInterface,
        server: RemoteServerInterface | None = None,
        logger: LogFile | None = None,
    ) -> None:
        # Interfaces are provided for future expansion; OSC is not
        # currently used by this feature but is kept for parity with
        # other features.
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self.server = server
        self._logger = logger
        self._running = False

        # Background worker thread that consumes Whisper transcripts.
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Tag used when reading from Whisper so this feature has an
        # independent view of the transcript.
        self._whisper_tag = "pet_word_game_feature"

        # Simple cooldown to avoid spamming shocks if the pet speaks
        # in long sentences or Whisper groups multiple pronouns into
        # one chunk.
        self._cooldown_seconds = 5.0
        self._cooldown_until: float = 0.0
        self._shock_strength: float = 20.0

        # Supported word games mapped to their handlers. Keys are
        # case-insensitive canonical names.
        self._game_handlers: Dict[str, Callable[[str], None]] = {
            "pronouns": self._process_pronouns_text,
        }
        self._active_game: str | None = None

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

        self._log(
            "event=init feature=word_game supported_games="
            + ",".join(sorted(self._game_handlers.keys()))
        )

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
            name="PetWordFeature",
            daemon=True,
        )
        self._thread = thread
        thread.start()

        self._log("event=start feature=word_game")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=word_game")

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        """Background loop that watches Whisper transcripts."""
        while not self._stop_event.is_set():
            active_game = self._active_word_game()
            if active_game != self._active_game:
                self._log(f"event=word_game_changed active={active_game or 'none'}")
                self._active_game = active_game

            if not active_game:
                if self._stop_event.wait(0.5):
                    break
                continue

            try:
                text = self.whisper.get_new_text(self._whisper_tag)
            except Exception:
                text = ""

            handler = self._game_handlers.get(self._normalise_game_name(active_game))
            if handler is None:
                if self._stop_event.wait(0.5):
                    break
                continue

            if text:
                handler(text)

            # Sleep briefly to limit CPU usage while still reacting
            # quickly to new speech.
            if self._stop_event.wait(0.5):
                break

    def _active_word_game(self) -> str | None:
        server = self.server
        if server is None:
            return None

        configs = getattr(server, "latest_settings_by_trainer", lambda: {})()
        for cfg in configs.values():
            game = str(cfg.get("word_game") or "").strip()
            if game and self._normalise_game_name(game) not in ("none", "off", "disabled"):
                return game

        return None

    @staticmethod
    def _normalise_game_name(name: str | None) -> str:
        return (name or "").strip().lower()

    def _process_pronouns_text(self, text: str) -> None:
        """Handler for the Pronouns word game."""
        if not text:
            return

        if self._contains_disallowed_pronouns(text):
            now = time.time()
            if now >= self._cooldown_until:
                self._deliver_correction(game="pronouns")
                self._cooldown_until = now + self._cooldown_seconds

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

    def _deliver_correction(self, game: str = "word_game") -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            # Use a modest default intensity and short pulse so that
            # this feature is usable out of the box without further
            # tuning. Values can be adjusted later or made configurable.
            self.pishock.send_shock(strength=self._shock_strength, duration=0.5)
            self._log(f"event=shock feature={game} strength={self._shock_strength}")
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
