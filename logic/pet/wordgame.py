from __future__ import annotations

import time
from typing import Callable, Dict, Set

from logic.feature import PetFeature


class WordFeature(PetFeature):
    """Pet word feature.

    Listens to pet speech via Whisper and runs the selected "word game".
    Each word game can apply its own rules; currently only the Pronouns
    game is implemented.
    """

    feature_name = "word_game"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._active = False

        # Simple cooldown to avoid spamming shocks if the pet speaks
        # in long sentences or Whisper groups multiple pronouns into
        # one chunk.
        self._cooldown_until: float = 0.0

        # Supported word games mapped to their handlers. Keys are
        # case-insensitive canonical names.
        self._game_handlers: Dict[str, Callable[[str], None]] = {
            "pronouns": self._process_pronouns_text,
        }
        self._active_game: str | None = None

        self._log(
            "event=init feature=word_game supported_games="
            + ",".join(sorted(self._game_handlers.keys()))
        )

    def start(self) -> None:
        if self._running:
            return

        # Ensure we only see future transcript text.
        try:
            self.whisper.reset_tag(self.feature_name)
        except Exception:
            pass

        self._start_worker(target=self._worker_loop, name="PetWordFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        """Background loop that watches Whisper transcripts."""
        while not self._stop_event.is_set():
            active_game = self._active_word_game()
            if active_game != self._active_game:
                self._log(f"event=word_game_changed active={active_game or 'none'}")
                self._active_game = active_game

            now_active = bool(active_game)
            if now_active and not self._active:
                # Word game just became active; ignore any old speech.
                try:
                    self.whisper.reset_tag(self.feature_name)
                except Exception:
                    pass
            self._active = now_active

            if not active_game:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            try:
                text = self.whisper.get_new_text(self.feature_name)
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
        configs = self._latest_trainer_settings()
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
                self._cooldown_until = now + self._cooldown_seconds()

    def _contains_disallowed_pronouns(self, text: str) -> bool:
        """Return True if the text includes first-person pronouns."""
        if not text:
            return False

        disallowed_tokens: Set[str] = {
            "i",
            "i'm",
            "i've",
            "i'll",
            "me",
            "my",
            "mine",
            "myself",
        }

        for raw_token in text.split():
            cleaned = "".join(ch for ch in raw_token if ch.isalpha() or ch in ("'", "’")).lower()
            if not cleaned:
                continue

            if cleaned.replace("’", "'") in disallowed_tokens:
                return True


        return False

    def _deliver_correction(self, game: str = "word_game") -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            self.pishock.send_shock(strength=self._shock_strength, duration=0.5)
            self._log(f"event=shock feature={game} strength={self._shock_strength}")
        except Exception:
            return
