from __future__ import annotations

from typing import Optional


class WhisperInterface:
    """Interface for running a local Whisper speech-to-text engine.

    This is a placeholder; the actual model loading and streaming audio
    handling can be implemented on top of this interface.
    """

    def __init__(self, input_device: Optional[str]) -> None:
        self.input_device = input_device
        self._running = False

    def start(self) -> None:
        """Start transcription for the configured input device."""
        self._running = True

    def stop(self) -> None:
        """Stop transcription."""
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running
