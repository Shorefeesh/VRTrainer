from __future__ import annotations

from typing import Optional
import pishock


class PiShockInterface:
    """Interface wrapper around the PiShock API.

    This keeps the rest of the codebase decoupled from the concrete
    Python-PiShock library while exposing a simple ``send_shock``
    helper used by trainer/pet features.
    """

    def __init__(self, username: str, api_key: str) -> None:
        self.username = username
        self.api_key = api_key

        self._connected: bool = False
        self._api: Optional[pishock.PiShockAPI] = None
        self._shocker: Optional[pishock.HTTPShocker] = None
        self._share_code: Optional[str] = None

    def configure_share_code(self, share_code: str) -> None:
        """Set the default share code to target when sending shocks.

        If no share code is configured, :meth:`send_shock` will be a
        no-op. This avoids crashing features if credentials are present
        but no concrete shocker has been selected yet.
        """
        self._share_code = share_code
        if self._api is not None:
            self._shocker = self._api.shocker(share_code)

    def start(self) -> None:
        """Initialise the PiShock API client and validate credentials."""
        if not self.username or not self.api_key:
            # Treat missing credentials as "not connected" but do not fail hard.
            self._connected = False
            self._api = None
            self._shocker = None
            return

        api = pishock.PiShockAPI(username=self.username, api_key=self.api_key)

        # verify_credentials() returns False on authentication failure.
        if not api.verify_credentials():
            self._connected = False
            self._api = None
            self._shocker = None
            return

        self._api = api
        self._connected = True

        # If we already have a share code configured, prepare a shocker instance.
        if self._share_code:
            self._shocker = api.shocker(self._share_code)

    def stop(self) -> None:
        """Tear down connection or cleanup resources."""
        self._connected = False
        self._api = None
        self._shocker = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def send_shock(
        self,
        strength: int,
        duration: float,
        *,
        share_code: Optional[str] = None,
    ) -> None:
        """Send a shock with the given strength and duration.

        Args:
            strength: Shock intensity (0-100).
            duration: Shock duration in seconds. Can be a float in the
                0.1–1.5 range to use the PiShock short-pulse feature,
                or an integer 0–15 for whole seconds.
            share_code: Optional override for the share code. If not
                given, the interface uses the configured default (see
                :meth:`configure_share_code`).

        This method is safe to call even when PiShock is not configured
        yet; in that case it simply returns without raising.
        """
        # Always emit an OSC parameter so the Trainer avatar can react
        # visually to shocks, even if the PiShock API itself is not
        # configured or connected.
        self._send_trainer_being_shocked(strength=strength, duration=duration)

        if not self._connected:
            return

        api = self._api
        if api is None:
            return

        # Determine which shocker/share code to use.
        code = share_code or self._share_code
        if not code:
            # No share code configured yet – nothing to do.
            return

        shocker = self._shocker
        if shocker is None or shocker.sharecode != code:  # type: ignore[attr-defined]
            shocker = api.shocker(code)
            self._shocker = shocker

        try:
            shocker.shock(duration=duration, intensity=strength)
        except Exception:
            # For now, swallow all errors so that a failed shock does
            # not bring down feature logic. Diagnostics can be added
            # later (logging, UI feedback, etc.).
            return

    # Internal helpers -------------------------------------------------
    def _send_trainer_being_shocked(self, strength: int, duration: float) -> None:
        """Send Trainer/BeingShocked OSC parameter for the given duration.

        The parameter is sent as a float whose value matches the shock
        strength so avatar logic can drive effects based on intensity.

        This helper is intentionally independent from PiShock connection
        status so that the OSC signal is still emitted when credentials
        are missing or invalid.
        """
        try:
            from pythonosc.udp_client import SimpleUDPClient
        except Exception:
            # If python-osc is not available, silently skip OSC output.
            return

        import threading
        import time

        # Clamp duration to a sensible non-negative value.
        safe_duration = max(float(duration), 0.0)
        # Normalise strength (0–100) to a 0–1 float for OSC.
        value = max(0.0, min(1.0, float(strength) / 100.0))

        def _worker() -> None:
            try:
                client = SimpleUDPClient("127.0.0.1", 9000)
                address = "/avatar/parameters/Trainer/BeingShocked"

                # Set parameter to the shock strength.
                client.send_message(address, value)

                if safe_duration > 0.0:
                    time.sleep(safe_duration)

                # Reset parameter back to zero.
                client.send_message(address, 0.0)
            except Exception:
                # Ignore any OSC errors so they never affect feature logic.
                return

        thread = threading.Thread(
            target=_worker,
            name="TrainerBeingShockedOSC",
            daemon=True,
        )
        thread.start()
