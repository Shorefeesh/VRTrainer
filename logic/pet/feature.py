import time

from logic.feature import Feature


class PetFeature(Feature):
    """Base class for pet-side features."""

    role = "pet"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._last_sample_log: float = 0

    def _active_trainer_configs(self) -> dict:
        configs = self._latest_trainer_settings()
        return {tid: cfg for tid, cfg in configs.items() if cfg.get(self.feature_name)}

    def _has_active_trainer(self) -> bool:
        return bool(self._active_trainer_configs())

    def _log_sample(self, stats: dict) -> None:
        now = time.time()

        if now - self._last_sample_log < 1.0:
            return

        self._last_sample_log = now

        text = " ".join([f"{key}={value:.3f}" for key, value in stats.items()])
        self._log(
            f"sample {text}"
        )

    def _check_cooldown(self, config: dict) -> bool:
        now = time.time()
        if now < self._cooldown_until:
            return False

        self._cooldown_until = now + self._scaled_cooldown(config)

        return True

    def _deliver_shock_range(self, config: dict, reason: str, value: float, threshold: float = 0.5, min: float = 0, max: float = 1, inverse: bool = False, trainer_id: str | None = None):
        if not self._check_cooldown(config):
            return

        shock_min, shock_max, duration = self._shock_params_range(config)

        if not inverse:
            scale = (value - threshold) / (max - threshold)
        else:
            scale = (threshold - value) / (threshold - min)
        strength = max(shock_min, min(shock_max, scale * shock_max))

        self.pishock.send_shock(strength=strength, duration=duration)

        self._log(
            f"shock reason={reason} threshold={threshold:.2f} value={value:.2f} strength={strength:.1f} duration={duration:.1f}" + f" trainer={trainer_id}" if trainer_id else ""
        )

    def _deliver_shock_single(self, config: dict, reason: str, trainer_id: str | None = None):
        if not self._check_cooldown(config):
            return

        strength, duration = self._shock_params_single(config)
        self.pishock.send_shock(strength=strength, duration=duration)
        self._log(
            f"shock reason={reason} strength={strength:.1f} duration={duration:.1f}" + f" trainer={trainer_id}" if trainer_id else ""
        )

    def _deliver_vibrate_single(self, config: dict, reason: str, trainer_id: str | None = None) -> None:
        if not self._check_cooldown(config):
            return

        strength, duration = self._shock_params_single(config)
        self.pishock.send_vibrate(strength=strength, duration=duration)
        self._log(
            f"vibrate reason={reason} strength={strength} duration={duration}" + f" trainer={trainer_id}" if trainer_id else ""
        )

    def _collect_events(self) -> dict:
        if self.server is None:
            return {}

        events = self.server.poll_feature_events(self.feature_name, limit=10)

        grouped: dict = {}
        for event in events:
            trainer_id = str(event.get("from_client") or "")
            if trainer_id:
                grouped.setdefault(trainer_id, []).append(event)
        return grouped
