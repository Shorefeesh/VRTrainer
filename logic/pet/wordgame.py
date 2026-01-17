from __future__ import annotations

import time
from typing import Callable, Dict, Set

from logic.feature import PetFeature


class WordFeature(PetFeature):
    """Pet word feature.

    Listens to pet speech via Whisper and runs the selected "word game".
    Each word game can apply its own rules; currently Pronouns, Letter E,
    Contractions, Swear Words, and Negativity are implemented.
    """

    feature_name = "word_game"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self.option_handlers: Dict[str, Callable[[dict, str], None]] = {
            "pronouns": self._process_pronouns_text,
            "letter_e": self._process_letter_e_text,
            "contractions": self._process_contractions_text,
            "swear_words": self._process_swear_words_text,
            "negativity": self._process_negativity_text,
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

    def _maybe_deliver_correction(self, config: dict, triggered: bool, game: str) -> None:
        """Apply cooldown logic and trigger a correction when needed."""
        if not triggered:
            return

        now = time.time()
        if now < self._cooldown_until:
            return

        self._deliver_correction(config, game=game)
        self._cooldown_until = now + self._scaled_cooldown(config)

    @staticmethod
    def _tokenise_text(text: str) -> list[str]:
        """Return lowercased tokens containing only letters and apostrophes."""
        if not text:
            return []

        tokens: list[str] = []
        for raw_token in text.split():
            cleaned = "".join(ch for ch in raw_token if ch.isalpha() or ch in ("'", "’")).lower()
            cleaned = cleaned.replace("’", "'")
            if cleaned:
                tokens.append(cleaned)
        return tokens

    def _process_pronouns_text(self, config: dict, text: str) -> None:
        """Handler for the Pronouns word game."""
        triggered = self._contains_disallowed_pronouns(text)
        self._maybe_deliver_correction(config, triggered, game="pronouns")

    def _process_letter_e_text(self, config: dict, text: str) -> None:
        """Handler for the Letter E word game."""
        triggered = self._contains_letter_e(text)
        self._maybe_deliver_correction(config, triggered, game="letter_e")

    def _process_contractions_text(self, config: dict, text: str) -> None:
        """Handler for the Contractions word game."""
        triggered = self._contains_contraction(text)
        self._maybe_deliver_correction(config, triggered, game="contractions")

    def _process_swear_words_text(self, config: dict, text: str) -> None:
        """Handler for the Swear Words word game."""
        triggered = self._contains_swear_words(text)
        self._maybe_deliver_correction(config, triggered, game="swear_words")

    def _process_negativity_text(self, config: dict, text: str) -> None:
        """Handler for the Negativity word game."""
        triggered = self._contains_negativity(text)
        self._maybe_deliver_correction(config, triggered, game="negativity")

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

        for token in self._tokenise_text(text):
            if token in disallowed_tokens:
                return True

        return False

    @staticmethod
    def _contains_letter_e(text: str) -> bool:
        """Return True if the text includes the letter 'e' or 'E'."""
        if not text:
            return False
        return any(ch.lower() == "e" for ch in text if ch.isalpha())

    def _contains_contraction(self, text: str) -> bool:
        """Return True if the text contains contractions."""
        if not text:
            return False
        return any(ch in ["'", "’"] for ch in text)

    def _contains_swear_words(self, text: str) -> bool:
        """Return True if the text contains swear words."""
        swear_words: Set[str] = {
            "ass",
            "asshole",
            "bastard",
            "bitch",
            "bullshit",
            "crap",
            "cunt",
            "damn",
            "dick",
            "dickhead",
            "douche",
            "douchebag",
            "fuck",
            "fucker",
            "fucking",
            "hell",
            "motherfucker",
            "piss",
            "prick",
            "shit",
            "shitty",
            "slut",
        }

        for token in self._tokenise_text(text):
            collapsed = token.replace("'", "")
            if token in swear_words or collapsed in swear_words:
                return True

        return False

    def _contains_negativity(self, text: str) -> bool:
        """Return True if the text contains negative wording."""
        negative_tokens: Set[str] = {
            "no",
            "not",
            "never",
            "none",
            "nothing",
            "nowhere",
            "nobody",
            "noone",
            "cannot",
            "cant",
            "dont",
            "wont",
            "shouldnt",
            "wouldnt",
            "couldnt",
            "isnt",
            "arent",
            "wasnt",
            "werent",
            "hasnt",
            "havent",
            "hadnt",
            "doesnt",
            "didnt",
            "aint",
            "stop",
            "bad",
            "worse",
            "worst",
            "hate",
            "awful",
            "terrible",
        }

        for token in self._tokenise_text(text):
            collapsed = token.replace("'", "")
            if token in negative_tokens or collapsed in negative_tokens:
                return True

        return False

    def _deliver_correction(self, config: dict, game: str = "word_game") -> None:
        """Trigger a corrective shock via PiShock."""
        strength, duration = self._shock_params_single(config)
        self.pishock.send_shock(strength, duration)
        self._log(f"shock game={game} strength={strength}")
