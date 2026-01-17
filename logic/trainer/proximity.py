from __future__ import annotations

from typing import Callable, Dict

from logic.feature import TrainerFeature


class TrainerProximityFeature(TrainerFeature):
    """Trainer-side whisper listener for proximity (summon) commands."""

    feature_name = "proximity"

    def __init__(
        self,
        *,
        config_provider: Callable[[], Dict[str, dict]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(config_provider=config_provider, **kwargs)

        self._command_phrases: list[str] = ["come here", "heel"]
        self._poll_interval: float = 0.1

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="TrainerProximityFeature")

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

            if text:
                self._maybe_send_summon(text)

            if self._stop_event.wait(self._poll_interval):
                break

    def _maybe_send_summon(self, text: str) -> None:
        normalised = self.normalise_text(text)
        if not normalised:
            return

        pet_configs = self._iter_pet_configs()
        if not pet_configs:
            return

        for pet_id, cfg in pet_configs.items():
            if not str(pet_id):
                continue
            if not cfg.get(self.feature_name):
                continue

            pet_names = self._extract_word_list(cfg, "names")
            if pet_names:
                recent_chunks = self.whisper.get_recent_text_chunks(count=3)
                recent_normalised = " ".join(self.normalise_list(recent_chunks))
                if not any(name in recent_normalised for name in pet_names):
                    continue

            if any(phrase in normalised for phrase in self._command_phrases):
                meta = {"feature": "proximity", "target_client": str(pet_id)}
                try:
                    self.server.send_command("summon", meta)
                    self._log(
                        f"summon pet={str(pet_id)[:8]}"
                    )
                    self._pulse_command_flag("Trainer/CommandSummon")
                except Exception:
                    continue
