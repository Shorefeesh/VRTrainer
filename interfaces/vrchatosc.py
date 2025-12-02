from __future__ import annotations


class VRChatOSCInterface:
    """Interface to VRChat OSC parameters.

    Listens for OSC messages from VRChat on localhost:9001 and tracks
    simple diagnostics that can be surfaced in the UI, such as how many
    messages have been received recently and which avatar parameters
    have been observed.
    """

    def __init__(self) -> None:
        from collections import deque
        from pathlib import Path
        import threading

        self._running = False
        self._host = "127.0.0.1"
        self._port = 9001

        self._lock = threading.Lock()
        self._message_times = deque()
        self._trainer_params_seen: set[str] = set()
        self._expected_trainer_params: set[str] = self._load_expected_trainer_params(Path(__file__).resolve())

        self._server = None
        self._thread = None

    @staticmethod
    def _load_expected_trainer_params(current_file: "Path") -> set[str]:
        """Load expected Trainer/<param> names from avatar/trainer.md if present."""
        from pathlib import Path

        root = current_file.parents[1]
        avatar_file = root / "avatar" / "trainer.md"
        if not avatar_file.exists():
            return set()

        expected: set[str] = set()
        content = avatar_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for token in stripped.split():
                if token.startswith("Trainer/"):
                    expected.add(token)
        return expected

    def start(self) -> None:
        """Start OSC handling and begin listening on localhost:9001."""
        if self._running:
            return

        try:
            from pythonosc.dispatcher import Dispatcher
            from pythonosc.osc_server import ThreadingOSCUDPServer
        except ImportError as exc:
            raise RuntimeError(
                "The 'python-osc' package is required for VRChat OSC. "
                "Install it with `pip install python-osc`."
            ) from exc

        import threading

        dispatcher = Dispatcher()
        dispatcher.set_default_handler(self._on_osc_message)

        try:
            server = ThreadingOSCUDPServer((self._host, self._port), dispatcher)
        except OSError:
            self._running = False
            return

        self._server = server
        self._running = True

        thread = threading.Thread(target=server.serve_forever, name="VRChatOSC", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        """Stop OSC handling."""
        self._running = False
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        self._thread = None

    # Internal helpers -------------------------------------------------
    def _on_osc_message(self, address: str, *_) -> None:
        """Default handler for all incoming OSC messages."""
        import time

        now = time.time()
        cutoff = now - 10.0

        with self._lock:
            self._message_times.append(now)
            while self._message_times and self._message_times[0] < cutoff:
                self._message_times.popleft()

            prefix = "/avatar/parameters/Trainer/"
            if address.startswith(prefix):
                trainer_suffix = address[len("/avatar/parameters/") :]
                self._trainer_params_seen.add(trainer_suffix)

    # Public diagnostics -----------------------------------------------
    def get_status_snapshot(self) -> dict:
        """Return a snapshot of recent OSC message and parameter status."""
        import time

        now = time.time()
        cutoff = now - 10.0

        with self._lock:
            while self._message_times and self._message_times[0] < cutoff:
                self._message_times.popleft()
            messages_last_10s = len(self._message_times)

            expected = set(self._expected_trainer_params)
            seen = set(self._trainer_params_seen)

        found = len(expected & seen)
        missing = sorted(expected - seen)

        return {
            "messages_last_10s": messages_last_10s,
            "expected_trainer_params_total": len(expected),
            "found_trainer_params": found,
            "missing_trainer_params": missing,
        }

    @property
    def is_running(self) -> bool:
        return self._running
