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

        # Supported word games mapped to their handlers. Keys are
        # case-insensitive canonical names.
        self._game_handlers: Dict[str, Callable[[str], None]] = {
            "pronouns": self._process_pronouns_text,
        }

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetWordFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        """Background loop that watches Whisper transcripts."""
        while not self._stop_event.is_set():
            config, game = self._active_word_game()

            if not game:
                self.whisper.reset_tag(self.feature_name)
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            handler = self._game_handlers.get(self._normalise_game_name(game))
            if handler is None:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            text = self.whisper.get_new_text(self.feature_name)

            if text:
                handler(config, text)

            if self._stop_event.wait(self._poll_interval):
                break

    def _active_word_game(self) -> Set[dict | None, str | None]:
        configs = self._latest_trainer_settings()
        for cfg in configs.values():
            game = str(cfg.get("word_game") or "").strip()
            if game and self._normalise_game_name(game) not in ("none", "off", "disabled"):
                return cfg, game

        return None, None

    @staticmethod
    def _normalise_game_name(name: str | None) -> str:
        return (name or "").strip().lower()

    def _process_pronouns_text(self, config: dict, text: str) -> None:
        """Handler for the Pronouns word game."""
        if self._contains_disallowed_pronouns(text):
            now = time.time()
            if now >= self._cooldown_until:
                self._deliver_correction(config, game="pronouns")
                self._cooldown_until = now + self._scaled_cooldown(config)

    def _contains_disallowed_pronouns(self, text: str) -> bool:
        """Return True if the text includes first-person pronouns."""
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

    def _deliver_correction(self, config: dict, game: str = "word_game") -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            strength, duration = self._scaled_strength_single(config)
            self.pishock.send_shock(strength, duration)
            self._log(f"shock game={game} strength={strength}")
        except Exception:
            return
