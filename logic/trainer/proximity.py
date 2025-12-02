from __future__ import annotations

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface


class ProximityFeature:
    """Trainer proximity feature.

    Observes distance between trainer and pet via OSC, using PiShock to
    enforce staying close enough.
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
