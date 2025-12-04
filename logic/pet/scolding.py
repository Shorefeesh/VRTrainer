from __future__ import annotations

import threading
import time
from typing import Iterable, List, Optional

from interfaces.pishock import PiShockInterface
from interfaces.server import RemoteServerInterface
from interfaces.vrchatosc import VRChatOSCInterface
from logic.logging_utils import LogFile


class ScoldingFeature:
    """Pet scolding feature.

    Listens for trainer scolding words forwarded from the trainer via the
    server and shocks the pet when detected. Runs entirely on the pet
    client.
    """

    def __init__(
        self,
        osc: VRChatOSCInterface,
        pishock: PiShockInterface,
        server: RemoteServerInterface | None = None,
        *,
        scolding_words: Optional[Iterable[str]] = None,
        scaling: Optional[dict[str, float]] = None,
        logger: LogFile | None = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.server = server
        self._running = False
        self._enabled = True
        self._logger = logger

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._scolding_phrases: List[str] = self._normalise_phrases(scolding_words or [])

        self._base_cooldown_seconds: float = 3.0
        self._cooldown_seconds: float = self._base_cooldown_seconds
        self._cooldown_until: float = 0.0

        self._base_shock_strength: float = 30
        self._shock_strength: float = self._base_shock_strength
        self._base_shock_duration: float = 0.5
        self._shock_duration: float = self._base_shock_duration
        self.set_scaling(
            delay_scale=(scaling or {}).get("delay_scale", 1.0),
            cooldown_scale=(scaling or {}).get("cooldown_scale", 1.0),
            duration_scale=(scaling or {}).get("duration_scale", 1.0),
            strength_scale=(scaling or {}).get("strength_scale", 1.0),
        )

        self._log("event=init feature=scolding runtime=pet")

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        thread = threading.Thread(
            target=self._worker_loop,
            name="PetScoldingFeature",
            daemon=True,
        )
        self._thread = thread
        thread.start()

        self._log("event=start feature=scolding runtime=pet")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("event=stop feature=scolding runtime=pet")

    # Internal helpers -------------------------------------------------
    def set_scaling(
        self,
        *,
        delay_scale: float = 1.0,
        cooldown_scale: float = 1.0,
        duration_scale: float = 1.0,
        strength_scale: float = 1.0,
    ) -> None:
        self._cooldown_seconds = max(0.0, self._base_cooldown_seconds * cooldown_scale)
        self._shock_strength = max(0.0, self._base_shock_strength * strength_scale)
        self._shock_duration = max(0.0, self._base_shock_duration * duration_scale)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._enabled:
                if self._stop_event.wait(0.5):
                    break
                continue

            if self._scolding_phrases and self._detect_remote_scold():
                now = time.time()
                if now >= self._cooldown_until:
                    self._deliver_scolding_shock()
                    self._cooldown_until = now + self._cooldown_seconds

            if self._stop_event.wait(0.5):
                break

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def _normalise_phrases(self, words: Iterable[str]) -> List[str]:
        return [self._normalise(word) for word in words if word and self._normalise(word)]

    @staticmethod
    def _normalise(text: str) -> str:
        if not text:
            return ""

        chars: List[str] = []
        for ch in text.lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch.isspace():
                chars.append(" ")
            else:
                chars.append(" ")

        cleaned = "".join(chars)
        return " ".join(cleaned.split())

    def _detect_remote_scold(self) -> bool:
        if self.server is None:
            return False

        events = self.server.poll_events(
            limit=5,
            predicate=lambda evt: (
                isinstance(evt, dict)
                and isinstance(evt.get("payload"), dict)
                and evt.get("payload", {}).get("type") == "scold"
                and evt.get("payload", {}).get("meta", {}).get("feature") == "scolding"
                and self._contains_scolding(evt.get("payload", {}).get("phrase", ""))
            ),
        )

        return bool(events)

    def _contains_scolding(self, text: str) -> bool:
        if not text:
            return False

        normalised = self._normalise(text)
        if not normalised:
            return False

        for phrase in self._scolding_phrases:
            if phrase and phrase in normalised:
                return True
        return False

    def _deliver_scolding_shock(self) -> None:
        try:
            strength = int(self._shock_strength)
            self.pishock.send_shock(strength=strength, duration=self._shock_duration)
            self._log(f"event=shock feature=scolding runtime=pet strength={strength}")
        except Exception:
            return

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return
