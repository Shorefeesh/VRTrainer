from logic.feature import Feature


class TrainerFeature(Feature):
    """Base class for trainer-side features."""

    role = "trainer"

    def _pulse_command_flag(self, flag_name: str) -> None:
        osc = self.osc
        if osc is None:
            return

        try:
            osc.pulse_parameter(flag_name, value_on=1, value_off=0, duration=0.2)
        except Exception:
            return

    def _has_active_pet(self) -> bool:
        configs = self._latest_trainer_settings()
        if not configs:
            return False

        flag = self.feature_name
        if not flag:
            return True

        return any(bool(cfg.get(self.feature_name or flag)) for cfg in configs.values())


class TrainerCommandFeature(TrainerFeature):
    """Base class for trainer-side features which triggers an event on specific command words."""

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._require_name: bool = False
        self._require_scold: bool = False
        self._send_default: bool = False
        self._command_phrases: dict[str, list[str]] = {}

    # Internal helpers -------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._has_active_pet():
                self.whisper.reset_tag(self.feature_name)
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            text = self.whisper.get_new_text(self.feature_name)

            pet_configs = self._config_map()
            if pet_configs and text:
                for pet_id, cfg in pet_configs.items():
                    if not cfg.get(self.feature_name):
                        continue

                    detected = self._detect_command(text, cfg)
                    if detected is None:
                        continue

                    meta = {"feature": self.feature_name, "target_client": str(pet_id)}
                    self.server.send_command(detected, meta)
                    self._log(
                        f"command pet={str(pet_id)[:8]} name={detected}"
                    )

                    self._pulse_command_flag("Trainer/Command")

            if self._stop_event.wait(self._poll_interval):
                break

    def _detect_command(self, text: str, cfg: dict) -> str | None:
        if not text:
            return None

        normalised = self.normalise_text(text)
        if not normalised:
            return None

        if self._require_name:
            names = self._extract_word_list(cfg, "names")
            recent_chunks = self.whisper.get_recent_text_chunks(count=3)
            recent_normalised = " ".join(self.normalise_list(recent_chunks))
            if not any(name in recent_normalised for name in names):
                return None

        if self._require_scold:
            scolds = self._extract_word_list(cfg, "scolding_words")
            if not any(scold in normalised for scold in scolds):
                return None

        for cmd, phrases in self._command_phrases.items():
            for phrase in phrases:
                if phrase and phrase in normalised:
                    return cmd

        if self._send_default:
            return self.feature_name

        return None
