from __future__ import annotations


from logic.trainer.feature import TrainerCommandFeature


class TrainerProximityFeature(TrainerCommandFeature):
    """Trainer-side whisper listener for proximity (summon) commands."""

    feature_name: str = "proximity"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._require_name: bool = True
        self._require_scold: bool = False
        self._send_default: bool = False

        self._command_phrases: dict[str, list[str]] = {
            "proximity": ["come here", "heel"]
        }

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="TrainerProximityFeature")

    def stop(self) -> None:
        self._stop_worker()
