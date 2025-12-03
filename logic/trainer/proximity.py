from __future__ import annotations

from typing import Iterable, List, Optional

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
        difficulty: Optional[str] = None,
        names: Optional[Iterable[str]] = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self._running = False
        self._enabled = True

        # Background polling loop.
        import threading

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Tunables – could become user settings later.
        self._poll_interval: float = 0.1
        self._proximity_threshold: float = 0.4  # values below this are "too far"
        self._breach_duration: float = 0.5  # seconds the pet must be far before shocking
        self._cooldown_seconds: float = 5.0
        self._cooldown_until: float = 0.0
        self._breach_started_at: float | None = None
        self._shock_strength_min: float = 20.0
        self._shock_strength_max: float = 80.0
        self._apply_difficulty(difficulty)

        # Whisper-driven summon command ("come here" / "heel").
        self._whisper_tag = "trainer_proximity_feature"
        self._pet_names: List[str] = self._normalise_phrases(names or [])
        self._command_phrases: List[str] = self._normalise_phrases(["come here", "heel"])
        self._command_timeout: float = 4.0
        self._command_target: float = 1
        self._pending_command_deadline: float | None = None

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        try:
            self.whisper.reset_tag(self._whisper_tag)
        except Exception:
            pass

        thread = self._thread = self._thread_factory()
        thread.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

    # Internal helpers -------------------------------------------------
    def _apply_difficulty(self, difficulty: Optional[str]) -> None:
        """Configure shock strength/cooldown based on difficulty label."""
        level = (difficulty or "Normal").strip().lower()
        if level == "easy":
            self._shock_strength_min = 5
            self._shock_strength_max = 30
            self._cooldown_seconds = 8.0
        elif level == "hard":
            self._shock_strength_min = 30
            self._shock_strength_max = 100
            self._cooldown_seconds = 2.0

    def _thread_factory(self):
        import threading

        return threading.Thread(
            target=self._worker_loop,
            name="TrainerProximityFeature",
            daemon=True,
        )

    def _worker_loop(self) -> None:
        """Poll proximity parameter and trigger shocks when too far."""
        import time

        while not self._stop_event.is_set():
            now = time.time()

            if not self._enabled:
                self._breach_started_at = None
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            # Listen for summon commands.
            try:
                text = self.whisper.get_new_text(self._whisper_tag)
            except Exception:
                text = ""

            if text and self._detect_summon_command(text):
                self._pending_command_deadline = now + self._command_timeout

            if self._pending_command_deadline is not None:
                if self._meets_command_target():
                    self._pending_command_deadline = None
                elif now >= self._pending_command_deadline and now >= self._cooldown_until:
                    self._deliver_correction()
                    self._cooldown_until = now + self._cooldown_seconds
                    self._pending_command_deadline = None

            # Rate-limit shocks.
            if now >= self._cooldown_until and self._is_too_far(now):
                self._deliver_correction()
                self._cooldown_until = now + self._cooldown_seconds
                self._breach_started_at = None

            if self._stop_event.wait(self._poll_interval):
                break

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable proximity enforcement."""

        self._enabled = bool(enabled)
        if not self._enabled:
            self._breach_started_at = None

    def _is_too_far(self, now: float) -> bool:
        """Return True if proximity has been below threshold long enough."""
        value = self.osc.get_float_param("Trainer/Proximity", default=1.0)

        if value >= self._proximity_threshold:
            self._breach_started_at = None
            return False

        if self._breach_started_at is None:
            self._breach_started_at = now
            return False

        return (now - self._breach_started_at) >= self._breach_duration

    def _deliver_correction(self) -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            # Scale intensity by how far away the pet is.
            proximity = self.osc.get_float_param("Trainer/Proximity", default=0.0)
            distance_factor = max(0.0, (self._proximity_threshold - proximity) / self._proximity_threshold)
            strength = max(self._shock_strength_min, min(self._shock_strength_max, int(distance_factor * self._shock_strength_max)))
            self.pishock.send_shock(strength=strength, duration=0.5)
        except Exception:
            return

    def _detect_summon_command(self, text: str) -> bool:
        """Return True when speech contains a summon command for the pet."""
        normalised = self._normalise_text(text)
        if not normalised:
            return False

        if self._pet_names:
            recent_chunks = self.whisper.get_recent_text_chunks(count=3)
            recent_normalised = " ".join(self._normalise_text(chunk) for chunk in recent_chunks if chunk)
            if not any(name in recent_normalised for name in self._pet_names):
                return False

        return any(phrase in normalised for phrase in self._command_phrases)

    def _meets_command_target(self) -> bool:
        """True if proximity is sufficiently close after a summon command."""
        proximity = self.osc.get_float_param("Trainer/Proximity", default=0.0)
        return proximity >= self._command_target

    @staticmethod
    def _normalise_phrases(phrases: Iterable[str]) -> List[str]:
        return [ProximityFeature._normalise_text(p) for p in phrases if ProximityFeature._normalise_text(p)]

    @staticmethod
    def _normalise_text(text: str) -> str:
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

        return " ".join("".join(chars).split())
