from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

from logic.pet.feature import PetFeature


@dataclass
class _TrainerForbiddenState:
    cooldown_until: float = 0.0


class ForbiddenWordsFeature(PetFeature):
    """Pet forbidden-words feature.

    Listens to pet speech via Whisper and applies corrections when any trainer
    configured forbidden word is spoken. Word lists are pulled from *all*
    trainers currently in the session so multiple trainers can contribute their
    own rules simultaneously.
    """

    feature_name = "forbidden_words"

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="PetForbiddenWordsFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._has_active_trainer():
                self.whisper.reset_tag(self.feature_name)
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            text = self.whisper.get_new_text(self.feature_name)
            normalised_text = self.normalise_text(text)

            if not normalised_text:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            active_configs = self._active_trainer_configs()

            for trainer_id, config in active_configs.items():
                phrases = self.normalise_list(config.get(self.feature_name, []))

                if not phrases:
                    continue

                match = self._match_forbidden(normalised_text, phrases)

                if match:
                    self._deliver_shock_single(config=config, reason=match, trainer_id=trainer_id)
                    break

            if self._stop_event.wait(self._poll_interval):
                break

    def _match_forbidden(self, normalised_text: str, phrases: List[str]) -> str | None:
        for phrase in phrases:
            if phrase in normalised_text:
                return phrase
        return None
