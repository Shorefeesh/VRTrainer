from __future__ import annotations

from typing import Callable, Dict

from logic.feature import TrainerFeature


class TrainerFocusFeature(TrainerFeature):
    """Trainer-side listener that relays focus-related voice cues."""

    feature_name = "focus"

    def __init__(
        self,
        *,
        config_provider: Callable[[], Dict[str, dict]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(config_provider=config_provider, **kwargs)

        self._default_command_phrases: list[str] = ["come here", "heel"]
        self._poll_interval: float = 0.1

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="TrainerFocusFeature")

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
                self._maybe_send_focus_command(text)

            if self._stop_event.wait(self._poll_interval):
                break

    def _maybe_send_focus_command(self, text: str) -> None:
        normalised = self.normalise_text(text)
        if not normalised:
            return

        pet_configs = self._iter_pet_configs()
        if not pet_configs:
            return

        for pet_id, cfg in pet_configs.items():
            if not str(pet_id):
                continue
            if not cfg.get("feature_focus"):
                continue

            penalties: list[str] = []
            pet_names = self._extract_word_list(cfg, "names")
            if pet_names and any(name in normalised for name in pet_names):
                penalties.append("name")

            if any(cmd in normalised for cmd in self._default_command_phrases):
                penalties.append("command_word")

            if not penalties:
                continue

            meta = {"feature": self.feature_name, "reasons": penalties, "text": normalised, "target_client": str(pet_id)}

            try:
                self.server.send_command("focus", meta)
                self._log(
                    f"command_start pet={str(pet_id)[:8]} reasons={'|'.join(penalties)} text={normalised}"
                )
                self._pulse_command_flag("Trainer/CommandFocus")
            except Exception:
                continue

    # Config helpers -------------------------------------------------

    def _extract_names(self, config: dict) -> list[str]:
        names = config.get("names") if isinstance(config, dict) else None
        pet_names = self.normalise_list(names)
        return pet_names
