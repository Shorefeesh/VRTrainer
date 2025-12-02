from __future__ import annotations

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface


class ScoldingFeature:
    """Trainer scolding feature.

    Detects scolding words spoken by the trainer via Whisper and uses
    PiShock to deliver feedback.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        whisper: WhisperInterface,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
