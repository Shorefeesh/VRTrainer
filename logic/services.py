from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface
from logic.pet.pronouns import PronounsFeature
from logic.pet.pull import PullFeature
from logic.trainer.focus import FocusFeature
from logic.trainer.proximity import ProximityFeature
from logic.trainer.scolding import ScoldingFeature
from logic.trainer.tricks import TricksFeature


@dataclass
class TrainerRuntime:
    """Holds running trainer interfaces and feature instances."""

    osc: VRChatOSCInterface
    pishock: PiShockInterface
    whisper: WhisperInterface
    features: List[Any] = field(default_factory=list)


@dataclass
class PetRuntime:
    """Holds running pet interfaces and feature instances."""

    osc: VRChatOSCInterface
    pishock: PiShockInterface
    whisper: WhisperInterface
    features: List[Any] = field(default_factory=list)


_trainer_runtime: Optional[TrainerRuntime] = None
_pet_runtime: Optional[PetRuntime] = None


def _build_trainer_interfaces(trainer_settings: dict, input_device: Optional[str]) -> TrainerRuntime:
    osc = VRChatOSCInterface()

    pishock = PiShockInterface(
        username=trainer_settings.get("pishock_username") or "",
        api_key=trainer_settings.get("pishock_api_key") or "",
        role="trainer",
    )

    whisper = WhisperInterface(input_device=input_device)

    # Start all interfaces before wiring features.
    osc.start()
    pishock.start()
    whisper.start()

    features: List[Any] = []

    if trainer_settings.get("feature_focus"):
        features.append(FocusFeature(osc=osc, pishock=pishock, whisper=whisper, difficulty=str(trainer_settings.get("difficulty") or "Normal")))

    if trainer_settings.get("feature_proximity"):
        features.append(ProximityFeature(osc=osc, pishock=pishock, whisper=whisper, difficulty=str(trainer_settings.get("difficulty") or "Normal")))

    if trainer_settings.get("feature_tricks"):
        features.append(TricksFeature(osc=osc, pishock=pishock, whisper=whisper, difficulty=str(trainer_settings.get("difficulty") or "Normal")))

    if trainer_settings.get("feature_scolding"):
        features.append(
            ScoldingFeature(
                osc=osc,
                pishock=pishock,
                whisper=whisper,
                scolding_words=trainer_settings.get("scolding_words") or [],
                difficulty=str(trainer_settings.get("difficulty") or "Normal"),
            )
        )

    for feature in features:
        if hasattr(feature, "start"):
            feature.start()

    return TrainerRuntime(osc=osc, pishock=pishock, whisper=whisper, features=features)


def _build_pet_interfaces(pet_settings: dict, input_device: Optional[str]) -> PetRuntime:
    osc = VRChatOSCInterface()

    pishock = PiShockInterface(
        username=pet_settings.get("pishock_username") or "",
        api_key=pet_settings.get("pishock_api_key") or "",
        role="pet",
    )

    whisper = WhisperInterface(input_device=input_device)

    osc.start()
    pishock.start()
    whisper.start()

    features: List[Any] = []

    if pet_settings.get("feature_ear_tail"):
        features.append(PullFeature(osc=osc, pishock=pishock, whisper=whisper))

    if pet_settings.get("feature_pronouns"):
        features.append(PronounsFeature(osc=osc, pishock=pishock, whisper=whisper))

    for feature in features:
        if hasattr(feature, "start"):
            feature.start()

    return PetRuntime(osc=osc, pishock=pishock, whisper=whisper, features=features)


def start_trainer(trainer_settings: dict, input_device: Optional[str]) -> None:
    """Launch all interfaces and construct feature instances for enabled features.

    This function is intended to be called when the Trainer tab's Start
    button is pressed.
    """
    global _trainer_runtime

    # If already running, stop the previous runtime first.
    if _trainer_runtime is not None:
        stop_trainer()

    _trainer_runtime = _build_trainer_interfaces(trainer_settings, input_device)


def stop_trainer() -> None:
    """Tear down running trainer interfaces and features, if any."""
    global _trainer_runtime

    runtime = _trainer_runtime
    if runtime is None:
        return

    # Stop features first so they no longer depend on interfaces.
    for feature in runtime.features:
        if hasattr(feature, "stop"):
            feature.stop()

    # Then stop interfaces.
    runtime.whisper.stop()
    runtime.pishock.stop()
    runtime.osc.stop()

    _trainer_runtime = None


def start_pet(pet_settings: dict, input_device: Optional[str]) -> None:
    """Launch all interfaces and construct feature instances for enabled pet features."""
    global _pet_runtime

    if _pet_runtime is not None:
        stop_pet()

    _pet_runtime = _build_pet_interfaces(pet_settings, input_device)


def stop_pet() -> None:
    """Tear down running pet interfaces and features, if any."""
    global _pet_runtime

    runtime = _pet_runtime
    if runtime is None:
        return

    for feature in runtime.features:
        if hasattr(feature, "stop"):
            feature.stop()

    runtime.whisper.stop()
    runtime.pishock.stop()
    runtime.osc.stop()

    _pet_runtime = None


def is_trainer_running() -> bool:
    """Return True if trainer services are currently active."""
    return _trainer_runtime is not None


def is_pet_running() -> bool:
    """Return True if pet services are currently active."""
    return _pet_runtime is not None


def get_trainer_osc_status() -> Optional[Dict[str, Any]]:
    """Return a snapshot of trainer OSC diagnostics, if running."""
    runtime = _trainer_runtime
    if runtime is None:
        return None
    return runtime.osc.get_status_snapshot()


def get_trainer_pishock_status() -> Optional[Dict[str, Any]]:
    """Return a snapshot of trainer PiShock status, if running."""
    runtime = _trainer_runtime
    if runtime is None:
        return None

    pishock = runtime.pishock
    return {
        "connected": pishock.is_connected,
        "has_credentials": bool(getattr(pishock, "username", "") and getattr(pishock, "api_key", "")),
    }


def get_pet_osc_status() -> Optional[Dict[str, Any]]:
    """Return a snapshot of pet OSC diagnostics, if running."""
    runtime = _pet_runtime
    if runtime is None:
        return None
    return runtime.osc.get_status_snapshot()


def get_pet_pishock_status() -> Optional[Dict[str, Any]]:
    """Return a snapshot of pet PiShock status, if running."""
    runtime = _pet_runtime
    if runtime is None:
        return None

    pishock = runtime.pishock
    return {
        "connected": pishock.is_connected,
        "has_credentials": bool(getattr(pishock, "username", "") and getattr(pishock, "api_key", "")),
    }


def get_trainer_whisper_log_text() -> str:
    """Return new Whisper transcript text for the trainer UI log.

    Uses a dedicated tag so UI logging does not interfere with
    feature-specific transcript consumption.
    """
    runtime = _trainer_runtime
    if runtime is None:
        return ""

    return runtime.whisper.get_new_text("trainer_ui_log")


def get_pet_whisper_log_text() -> str:
    """Return new Whisper transcript text for the pet UI log."""
    runtime = _pet_runtime
    if runtime is None:
        return ""

    return runtime.whisper.get_new_text("pet_ui_log")
