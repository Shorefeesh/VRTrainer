from __future__ import annotations


from logic.feature import TrainerCommandFeature


class TrainerFocusFeature(TrainerCommandFeature):
    """Trainer-side listener that relays focus-related voice cues."""

    feature_name = "focus"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._require_name: bool = True
        self._require_scold: bool = False
        self._send_default: bool = True

    def start(self) -> None:
        self._start_worker(target=self._worker_loop, name="TrainerFocusFeature")

    def stop(self) -> None:
        self._stop_worker()
