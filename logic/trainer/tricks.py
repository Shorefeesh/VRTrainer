from __future__ import annotations

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface


class _PendingCommand:
    """Lightweight container for a command that is waiting to be completed."""

    def __init__(self, name: str, started_at: float, deadline: float) -> None:
        self.name = name
        self.started_at = started_at
        self.deadline = deadline


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
        *,
        names: list[str] | None = None,
        difficulty: str | None = None,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self._running = False

        import threading

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Whisper tag so this feature only consumes its own transcript stream.
        self._whisper_tag = "trainer_tricks_feature"

        # Names that must be present in a spoken command (if any are configured).
        self._pet_names = [self._normalise_text(name) for name in (names or []) if self._normalise_text(name)]

        # Timing / strength tunables.
        self._poll_interval: float = 0.2
        self._command_timeout: float = 5.0
        self._cooldown_seconds: float = 2.0
        self._cooldown_until: float = 0.0
        self._shock_strength: int = 35
        self._apply_difficulty(difficulty)

        # Active command state.
        self._pending: _PendingCommand | None = None

        # Command vocabulary. Keys are internal names; values are lists
        # of phrases that should trigger the command when paired with
        # a pet name in speech.
        self._command_phrases: dict[str, list[str]] = {
            "paw": ["paw", "poor", "pour", "pore"],
            "sit": ["sit"],
            "lay_down": ["lay down", "laydown", "lie down", "layed down"],
            "beg": ["beg"],
            "play_dead": ["play dead", "playdead", "played dead"],
            "roll_over": ["rollover", "roll over"],
        }

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        try:
            self.whisper.reset_tag(self._whisper_tag)
        except Exception:
            # Whisper may not be fully initialised; continue regardless.
            pass

        import threading

        thread = threading.Thread(
            target=self._worker_loop,
            name="TrainerTricksFeature",
            daemon=True,
        )
        self._thread = thread
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
    def _apply_difficulty(self, difficulty: str | None) -> None:
        """Adjust timing/strength based on difficulty label."""
        level = (difficulty or "Normal").strip().lower()
        if level == "easy":
            self._command_timeout = 6.0
            self._shock_strength = 25
            self._cooldown_seconds = 3.0
        elif level == "hard":
            self._command_timeout = 4.0
            self._shock_strength = 45
            self._cooldown_seconds = 1.5

    def _worker_loop(self) -> None:
        """Main loop: read Whisper text, detect commands, check completion."""
        import time

        while not self._stop_event.is_set():
            now = time.time()

            # Check for newly spoken commands.
            try:
                text = self.whisper.get_new_text(self._whisper_tag)
            except Exception:
                text = ""

            detected = self._detect_command(text)
            if detected is not None:
                self._pending = _PendingCommand(
                    name=detected,
                    started_at=now,
                    deadline=now + self._command_timeout,
                )

            # Evaluate the active command, if any.
            if self._pending is not None:
                if self._is_command_completed(self._pending.name):
                    self._pending = None
                elif now >= self._pending.deadline and now >= self._cooldown_until:
                    self._deliver_failure()
                    self._cooldown_until = now + self._cooldown_seconds
                    self._pending = None

            if self._stop_event.wait(self._poll_interval):
                break

    def _detect_command(self, text: str) -> str | None:
        """Return the internal command name if text contains name+command."""
        if not text:
            return None

        normalised = self._normalise_text(text)
        if not normalised:
            return None

        # Require a pet name match if any are configured, using a short
        # look-back window to tolerate Whisper chunking that splits the
        # name from the command phrase.
        if self._pet_names:
            recent_chunks = self.whisper.get_recent_text_chunks(count=3)
            recent_normalised = " ".join(
                self._normalise_text(chunk) for chunk in recent_chunks if chunk
            )
            if not any(name in recent_normalised for name in self._pet_names):
                return None

        # Detect command phrases in the current text chunk(s).
        for cmd, phrases in self._command_phrases.items():
            for phrase in phrases:
                if phrase and phrase in normalised:
                    return cmd
        return None

    def _is_command_completed(self, command: str) -> bool:
        """Check OSC parameters to confirm a command was completed."""
        if command == "paw":
            return self.osc.get_bool_param("Trainer/Paw", default=False)
        elif command == "sit":
            return self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "lay_down":
            return self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "beg":
            return not self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "play_dead":
            return not self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)
        elif command == "roll_over":
            return not self.osc.get_bool_param("Trainer/HandNearFloor", default=False) \
                   and not self.osc.get_bool_param("Trainer/FootNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HipsNearFloor", default=False) \
                   and self.osc.get_bool_param("Trainer/HeadNearFloor", default=False)

        return False

    def _deliver_failure(self) -> None:
        """Shock the pet for failing to perform the trick."""
        try:
            self.pishock.send_shock(strength=self._shock_strength, duration=0.5)
        except Exception:
            # Never let PiShock errors break the feature loop.
            return

    @staticmethod
    def _normalise_text(text: str) -> str:
        """Lowercase and strip punctuation for loose matching."""
        if not text:
            return ""

        chars: list[str] = []
        for ch in text.lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch.isspace():
                chars.append(" ")
            else:
                chars.append(" ")

        return " ".join("".join(chars).split())
