from __future__ import annotations

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface


class FocusFeature:
    """Trainer focus feature.

    Uses VRChat OSC to determine whether the pet is looking at the
    trainer and PiShock to deliver consequences. Whisper may be used
    later for voice interaction nuances.
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
