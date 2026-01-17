from __future__ import annotations

from typing import Callable, Dict

from logic.feature import TrainerFeature


class TrainerScoldingFeature(TrainerFeature):
    """Trainer-side listener that forwards scolding words to the server."""

    feature_name = "scolding"

    def __init__(
        self,
        *,
        config_provider: Callable[[], Dict[str, dict]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(config_provider=config_provider, **kwargs)

        self._poll_interval = 0.2

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="TrainerScoldingFeature")

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
                self._maybe_send_scold(text)

            if self._stop_event.wait(self._poll_interval):
                break

    def _maybe_send_scold(self, text: str) -> None:
        normalised = self.normalize_text(text)
        if not normalised:
            return

        pet_configs = self._iter_pet_configs()
        if not pet_configs:
            return

        for pet_id, cfg in pet_configs.items():
            if not cfg.get("feature_scolding"):
                continue

            phrases = self._extract_word_list(cfg, "scolding_words")
            if not phrases:
                continue

            if any(phrase in normalised for phrase in phrases):
                meta = {"feature": "scolding", "target_client": str(pet_id)}
                try:
                    self.server.send_command(normalised, meta)
                    self._log(
                        "event=scold feature=scolding runtime=trainer pet="
                        + str(pet_id)[:8]
                        + " text="
                        + normalised
                    )
                    self._pulse_command_flag("Trainer/CommandScold")
                except Exception:
                    continue

    # Config helpers -------------------------------------------------
    def _iter_pet_configs(self) -> Dict[str, dict]:
        return self._config_map()
