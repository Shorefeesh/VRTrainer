from __future__ import annotations


class PiShockInterface:
    """Interface wrapper around the PiShock API.

    The concrete shock logic can be implemented later; for now this
    class simply tracks basic connection lifecycle.
    """

    def __init__(self, username: str, api_key: str) -> None:
        self.username = username
        self.api_key = api_key
        self._connected = False

    def start(self) -> None:
        """Establish connection or perform any required setup."""
        # Real implementation would validate credentials / prepare client.
        self._connected = True

    def stop(self) -> None:
        """Tear down connection or cleanup resources."""
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected
