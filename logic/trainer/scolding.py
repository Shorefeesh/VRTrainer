from __future__ import annotations


from logic.trainer.feature import TrainerCommandFeature


class TrainerScoldingFeature(TrainerCommandFeature):
    """Trainer-side listener that forwards scolding words to the server."""

    feature_name: str = "scolding"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._require_name: bool = False
        self._require_scold: bool = True
        self._send_default: bool = True

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="TrainerScoldingFeature")

    def stop(self) -> None:
        self._stop_worker()
