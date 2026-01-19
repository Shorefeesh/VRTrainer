from __future__ import annotations

from typing import Optional, TYPE_CHECKING
import pishock
import logging

if TYPE_CHECKING:
    from interfaces.vrchatosc import VRChatOSCInterface


class PiShockInterface:
    """Interface wrapper around the PiShock API.

    This keeps the rest of the codebase decoupled from the concrete
    Python-PiShock library while exposing a simple ``send_shock``
    helper used by trainer/pet features.
    """

    def __init__(
        self,
        username: str,
        api_key: str,
        share_code: str,
        shocker_id: str,
        role: str = "trainer",
        osc: "VRChatOSCInterface" = None,
    ) -> None:
        """Create a new PiShock interface.

        Args:
            username: PiShock account username.
            api_key: PiShock API key.
            role: Which runtime is using this interface, ``\"trainer\"`` or ``\"pet\"``.
            osc: VRChat OSC interface for mirroring shocks to avatar parameters.
        """
        self.username: Optional[str] = username
        self.api_key: Optional[str] = api_key
        self.share_code: Optional[str] = share_code
        self.shocker_id: Optional[int] = int(shocker_id)
        self._osc: Optional["VRChatOSCInterface"] = osc

        self.logger = logging.getLogger(__name__)

        # Normalise role so unexpected values fall back to trainer
        self._role = "pet" if role == "pet" else "trainer"
        # Only the pet runtime should ever drive the real PiShock/OSC
        # outputs. On the trainer side, the interface remains inert and
        # relies on server-mediated actions instead.
        self._enabled: bool = self._role == "pet"

        self._connected: bool = False
        self._api: Optional[pishock.PiShockAPI | pishock.SerialAPI] = None
        self._shocker: Optional[pishock.HTTPShocker | pishock.SerialShocker] = None
        self._api_mode: str = "serial"

    def start(self) -> None:
        """Initialise the PiShock API client and validate credentials."""
        if not self._enabled:
            # Trainer side: intentionally skip PiShock initialisation.
            self._connected = False
            self._api = None
            self._shocker = None
            self.logger.info("PiShock not enabled")
            return

        if not self.username or not self.api_key or not self.share_code:
            # Treat missing credentials as "not connected" but do not fail hard.
            self._connected = False
            self._api = None
            self._shocker = None
            self.logger.info("PiShock no details")
            return

        try:
            api = pishock.SerialAPI(port=None)
            self.logger.info(api.info())
        except pishock.zap.serialapi.SerialAutodetectError:
            api = pishock.PiShockAPI(username=self.username, api_key=self.api_key)
            self._api_mode = "online"

        # verify_credentials() returns False on authentication failure.
        if self._api_mode == "web" and not api.verify_credentials():
            self._connected = False
            self._api = None
            self._shocker = None
            self.logger.info("PiShock verify fail")
            return

        self._api = api
        self._connected = True

        if self._api_mode == "serial":
            self._shocker = api.shocker(self.shocker_id)
        else:
            self._shocker = api.shocker(self.share_code)

        self._shocker.vibrate(duration=1, intensity=100)

        self.logger.info("PiShock verify success")

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
        self.logger.info("PiShock sending shock start")

        if not self._enabled:
            self.logger.info("PiShock not enabled")
            return

        if not self._connected:
            self.logger.info("PiShock not connected")
            return

        shocker = self._shocker
        if shocker is None:
            self.logger.info("PiShock no shocker")
            return

        safe_strength = max(0, min(100, int(strength)))
        safe_duration = max(0.0,  min(15.0, float(duration)))

        self._send_shock_osc(strength=safe_strength, duration=1)

        try:
            shocker.shock(duration=safe_duration, intensity=safe_strength)
            self.logger.info("PiShock sending shock done")
        except Exception as exc:
            self.logger.info(f"PiShock sending shock failed: {exc}")

    def send_vibrate(
        self,
        strength: int,
        duration: float,
    ) -> None:
        """Send a vibration with the given strength and duration.

        Args:
            strength: Vibration intensity (0-100).
            duration: Vibration duration in seconds. Can be a float in the
                0-1 range or an integer 0–15 for whole seconds.
        """
        self.logger.info("PiShock sending vibration start")

        if not self._enabled:
            self.logger.info("PiShock not enabled")
            return

        if not self._connected:
            self.logger.info("PiShock not connected")
            return

        shocker = self._shocker
        if shocker is None:
            self.logger.info("PiShock no shocker")
            return

        safe_strength = max(0, min(100, int(strength)))
        safe_duration = max(0.0,  min(15.0, float(duration)))

        try:
            shocker.vibrate(duration=safe_duration, intensity=safe_strength)
            self.logger.info("PiShock sending vibration done")
        except Exception as exc:
            self.logger.info(f"PiShock sending vibration failed: {exc}")

    # Internal helpers -------------------------------------------------
    def _send_shock_osc(self, strength: int, duration: float) -> None:
        """Send OSC parameters for the given shock """
        # Normalise strength (0–100) to a 0–1 float for OSC.
        value = max(0.0, min(1.0, float(strength) / 100.0))

        self._osc.pulse_parameter(
            "Trainer/BeingShocked",
            value_on=value,
            value_off=0.0,
            duration=duration,
        )
