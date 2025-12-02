from __future__ import annotations


class VRChatOSCInterface:
    """Interface to VRChat OSC parameters.

    This is a placeholder implementation that can later be expanded to
    manage the OSC client/server, subscriptions, and callbacks.
    """

    def __init__(self) -> None:
        self._running = False

    def start(self) -> None:
        """Start OSC handling."""
        self._running = True

    def stop(self) -> None:
        """Stop OSC handling."""
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running
