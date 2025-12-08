from __future__ import annotations

from typing import Optional
import pishock


class PiShockInterface:
    """Interface wrapper around the PiShock API.

    This keeps the rest of the codebase decoupled from the concrete
    Python-PiShock library while exposing a simple ``send_shock``
    helper used by trainer/pet features.
    """

    def __init__(self, username: str, api_key: str, share_code: str, role: str = "trainer") -> None:
        """Create a new PiShock interface.

        Args:
            username: PiShock account username.
            api_key: PiShock API key.
            role: Which runtime is using this interface, ``\"trainer\"``
                or ``\"pet\"``.
        """
        self.username: Optional[str] = username
        self.api_key: Optional[str] = api_key
        self.share_code: Optional[str] = share_code

        # Normalise role so unexpected values fall back to trainer
        self._role = "pet" if role == "pet" else "trainer"
        # Only the pet runtime should ever drive the real PiShock/OSC
        # outputs. On the trainer side, the interface remains inert and
        # relies on server-mediated actions instead.
        self._enabled: bool = self._role == "pet"

        self._connected: bool = False
        self._api: Optional[pishock.PiShockAPI] = None
        self._shocker: Optional[pishock.HTTPShocker] = None

    def start(self) -> None:
        """Initialise the PiShock API client and validate credentials."""
        if not self._enabled:
            # Trainer side: intentionally skip PiShock initialisation.
            self._connected = False
            self._api = None
            self._shocker = None
            print("PiShock not enabled")
            return

        if not self.username or not self.api_key or not self.share_code:
            # Treat missing credentials as "not connected" but do not fail hard.
            self._connected = False
            self._api = None
            self._shocker = None
            print("PiShock no details")
            return

        api = pishock.PiShockAPI(username=self.username, api_key=self.api_key)

        # verify_credentials() returns False on authentication failure.
        if not api.verify_credentials():
            self._connected = False
            self._api = None
            self._shocker = None
            print("PiShock verify fail")
            return

        self._api = api
        self._connected = True

        self._shocker = api.shocker(self.share_code)

        print("PiShock verify success")

    def stop(self) -> None:
        """Tear down connection or cleanup resources."""
        self._connected = False
        self._api = None
        self._shocker = None

    @property
    def is_connected(self) -> bool:
        return self._enabled and self._connected

    @property
    def enabled(self) -> bool:
        return self._enabled

    def send_shock(
        self,
        strength: int,
        duration: float,
    ) -> None:
        """Send a shock with the given strength and duration.

        Args:
            strength: Shock intensity (0-100).
            duration: Shock duration in seconds. Can be a float in the
                0-1 range or an integer 0–15 for whole seconds.
        """
        print("PiShock sending shock start")

        if not self._enabled:
            print("PiShock not enabled")
            return

        # Always emit an OSC parameter so the avatars can react visually
        # to shocks, even if the PiShock API itself is not configured
        # or connected.
        self._send_shock_osc(strength=strength, duration=duration)

        if not self._connected:
            print("PiShock not connected")
            return

        shocker = self._shocker
        if shocker is None:
            print("PiShock no shocker")
            return

        print("PiShock sending shock start2")

        shocker.shock(duration=duration, intensity=strength)

        print("PiShock sending shock done")

    def send_vibrate(
        self,
        strength: int,
        duration: float,
    ) -> None:
        """Send a vibrate with the given strength and duration.

        Args:
            strength: Vibrate intensity (0-100).
            duration: Vibrate duration in seconds. Can be a float in the
                0-1 range or an integer 0–15 for whole seconds.
        """
        if not self._enabled:
            return

        # Always emit an OSC parameter so the avatars can react visually
        # to shocks, even if the PiShock API itself is not configured
        # or connected.
        self._send_shock_osc(strength=strength, duration=duration)

        if not self._connected:
            return

        shocker = self._shocker
        if shocker is None:
            return

        shocker.vibrate(duration=duration, intensity=strength)

    # Internal helpers -------------------------------------------------
    def _send_shock_osc(self, strength: int, duration: float) -> None:
        """Send OSC parameters for the given shock based on runtime role.

        The parameters are sent as floats whose value matches the shock
        strength (normalised to 0–1) so avatar logic can drive effects
        based on intensity.

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

        addresses = ["/avatar/parameters/Trainer/BeingShocked"]
        thread_name = "PetBeingShockedOSC"

        def _worker() -> None:
            try:
                client = SimpleUDPClient("127.0.0.1", 9000)

                # Set parameters to the shock strength.
                for addr in addresses:
                    client.send_message(addr, value)

                if safe_duration > 0.0:
                    time.sleep(safe_duration)

                # Reset parameters back to zero.
                for addr in addresses:
                    client.send_message(addr, 0.0)
            except Exception:
                # Ignore any OSC errors so they never affect feature logic.
                return

        thread = threading.Thread(
            target=_worker,
            name=thread_name,
            daemon=True,
        )
        thread.start()
