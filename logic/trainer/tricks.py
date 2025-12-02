from __future__ import annotations

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface


class TricksFeature:
    """Trainer tricks feature.

    Listens for commands via Whisper and validates completion through
    OSC parameters, applying shocks via PiShock if required.
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
