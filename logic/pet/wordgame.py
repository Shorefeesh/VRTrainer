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

        self.option_handlers: Dict[str, Callable[[dict, str], None]] = {
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
            if not self._has_active_trainer():
                self.whisper.reset_tag(self.feature_name)
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            active_configs = self._active_trainer_configs()

            text = self.whisper.get_new_text(self.feature_name)

            for trainer_id, config in active_configs.items():
                if not text:
                    continue

                handlers = self.option_handlers or {}
                selected_option = config.get(self.option_config_key)
                handler = handlers.get(selected_option) if isinstance(handlers, dict) else None

                if handler is None and isinstance(handlers, dict) and handlers:
                    # Fall back to the first available option for robustness.
                    handler = handlers[next(iter(handlers.keys()))]

                if handler is not None:
                    handler(config, text)

            if self._stop_event.wait(self._poll_interval):
                break

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
        strength, duration = self._shock_params_single(config)
        self.pishock.send_shock(strength, duration)
        self._log(f"shock game={game} strength={strength}")
