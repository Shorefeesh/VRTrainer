from __future__ import annotations


from logic.feature import TrainerCommandFeature


class TrainerTricksFeature(TrainerCommandFeature):
    """Trainer-side whisper listener for trick commands."""

    feature_name: str = "tricks"

    def __init__(
        self,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._require_name: bool = True
        self._require_scold: bool = False
        self._send_default: bool = False

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
