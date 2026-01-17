from __future__ import annotations

from typing import Callable, Dict

from logic.feature import TrainerFeature


class TrainerTricksFeature(TrainerFeature):
    """Trainer-side whisper listener for trick commands."""

    feature_name = "tricks"

    def __init__(
        self,
        *,
        config_provider: Callable[[], Dict[str, dict]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(config_provider=config_provider, **kwargs)

        self._poll_interval: float = 0.2
        self._command_phrases: dict[str, list[str]] = {
            "paw": ["paw", "poor", "pour", "pore"],
            "sit": ["sit"],
            "lay_down": ["lay down", "laydown", "lie down", "layed down"],
            "beg": ["beg"],
            "play_dead": ["play dead", "playdead", "played dead"],
            "roll_over": ["rollover", "roll over"],
        }

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="TrainerTricksFeature")

    def stop(self) -> None:
        self._stop_worker()

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._has_active_pet():
                self.whisper.reset_tag(self.feature_name)
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            try:
                text = self.whisper.get_new_text(self.feature_name)
            except Exception:
                text = ""

            pet_configs = self._iter_pet_configs()
            if pet_configs and text:
                for pet_id, cfg in pet_configs.items():
                    if not str(pet_id):
                        continue
                    if not cfg.get(self.feature_name):
                        continue

                    pet_names = self._extract_word_list(cfg, "names")
                    detected = self._detect_command(text, pet_names)
                    if detected is None:
                        continue

                    meta = {"feature": self.feature_name, "target_client": str(pet_id)}
                    try:
                        self.server.send_command(detected, meta)
                        self._log(
                            f"command_start pet={str(pet_id)[:8]} trick={detected}"
                        )
                        if first_sent is None:
                            first_sent = detected
                    except Exception:
                        continue

                    self._pulse_command_flag("Trainer/CommandTrick")

            if self._stop_event.wait(self._poll_interval):
                break

    def _iter_pet_configs(self) -> Dict[str, dict]:
        return self._config_map()

    def _detect_command(self, text: str, pet_names: list[str]) -> str | None:
        if not text:
            return None

        normalised = self.normalize_text(text)
        if not normalised:
            return None

        if pet_names:
            recent_chunks = self.whisper.get_recent_text_chunks(count=3)
            recent_normalised = " ".join(self.normalize_list(recent_chunks))
            if not any(name in recent_normalised for name in pet_names):
                return None

        for cmd, phrases in self._command_phrases.items():
            for phrase in phrases:
                if phrase and phrase in normalised:
                    return cmd
        return None
