from __future__ import annotations

from typing import Iterable, List, Optional

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
        difficulty: Optional[str] = None,
        names: Optional[Iterable[str]] = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self._running = False
        self._enabled = True

        # Background worker that continually updates a simple "focus
        # meter" based on whether the pet is looking at the trainer.
        import threading

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Focus meter state and tunables. The meter is clamped to 0–1:
        # it fills while the pet is focused and drains while distracted.
        self._focus_meter: float = 1.0
        self._poll_interval: float = 0.1  # seconds between polls
        self._fill_rate: float = 0.2  # meter points per second while focused
        self._drain_rate: float = 0.02  # meter points per second while distracted
        self._shock_threshold: float = 0.2  # trigger a shock when meter dips below

        # Cooldown so repeated neglect doesn't spam the shocker.
        self._cooldown_seconds: float = 5.0
        self._cooldown_until: float = 0.0

        self._shock_strength_min: float = 20.0
        self._shock_strength_max: float = 80.0

        # Track time between iterations for smoother meter integration.
        self._last_tick: float | None = None

        # Listening for the pet's name being spoken should drain focus
        # even if OSC still reports eye contact. Use a dedicated Whisper
        # tag so this feature does not consume transcripts needed
        # elsewhere.
        self._whisper_tag: str = "trainer_focus_feature"
        self._pet_names: List[str] = self._normalise_phrases(names or [])
        self._name_penalty: float = 0.15  # meter points removed per detected name call

        self._apply_difficulty(difficulty)


    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        # Start reading from the current end of the transcript so we
        # only react to new speech after the feature starts.
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
            self._fill_rate = 0.3
            self._drain_rate = 0.01
            self._shock_strength_min = 5
            self._shock_strength_max = 30
            self._cooldown_seconds = 8.0
        elif level == "hard":
            self._fill_rate = 0.2
            self._drain_rate = 0.04
            self._shock_strength_min = 30
            self._shock_strength_max = 100
            self._cooldown_seconds = 2.0

    def _thread_factory(self):
        import threading

        return threading.Thread(
            target=self._worker_loop,
            name="TrainerFocusFeature",
            daemon=True,
        )

    def _worker_loop(self) -> None:
        """Continuously adjust the focus meter and correct lapses."""
        import time

        self._last_tick = time.time()

        while not self._stop_event.is_set():
            now = time.time()
            dt = max(0.0, now - (self._last_tick or now))
            self._last_tick = now

            if not self._enabled:
                if self._stop_event.wait(self._poll_interval):
                    break
                continue

            self._apply_name_penalty()
            self._update_meter(dt)

            if self._should_shock(now):
                self._deliver_correction()
                self._cooldown_until = now + self._cooldown_seconds

            if self._stop_event.wait(self._poll_interval):
                break

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable focus monitoring without stopping the thread."""

        self._enabled = bool(enabled)

    def _update_meter(self, dt: float) -> None:
        """Raise or lower the focus meter based on OSC boolean."""
        focused = self.osc.get_bool_param("Trainer/Focus", default=False)
        delta = (self._fill_rate if focused else -self._drain_rate) * dt
        self._focus_meter = max(0.0, min(1.0, self._focus_meter + delta))

    def _apply_name_penalty(self) -> None:
        """Drain the meter when the pet's name is called out loud."""
        if not self._pet_names:
            return

        try:
            text = self.whisper.get_new_text(self._whisper_tag)
        except Exception:
            return

        if not text:
            return

        normalised = self._normalise(text)
        if not normalised:
            return

        if any(name in normalised for name in self._pet_names):
            self._focus_meter = max(0.0, self._focus_meter - self._name_penalty)

    def _should_shock(self, now: float) -> bool:
        """Return True when focus is low and cooldown expired."""
        if now < self._cooldown_until:
            return False
        return self._focus_meter <= self._shock_threshold

    def _deliver_correction(self) -> None:
        """Trigger a corrective shock via PiShock."""
        try:
            # Scale strength with how empty the meter is (20–80).
            deficit = (self._shock_threshold - self._focus_meter) / self._shock_threshold
            strength = max(self._shock_strength_min, min(self._shock_strength_max, int(deficit * self._shock_strength_max)))
            self.pishock.send_shock(strength=strength, duration=0.5)
        except Exception:
            # Never let PiShock errors break the feature loop.
            return

    @staticmethod
    def _normalise_phrases(words: Iterable[str]) -> List[str]:
        """Normalise configured pet names for matching."""
        return [FocusFeature._normalise(word) for word in words if word and FocusFeature._normalise(word)]

    @staticmethod
    def _normalise(text: str) -> str:
        """Lowercase, strip punctuation, and collapse whitespace."""
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
