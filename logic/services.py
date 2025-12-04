from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface
from interfaces.server import DummyServerInterface
from logic.logging_utils import SessionLogManager
from logic.pet.focus import FocusFeature
from logic.pet.pronouns import PronounsFeature
from logic.pet.proximity import ProximityFeature
from logic.pet.pull import PullFeature
from logic.pet.scolding import ScoldingFeature
from logic.pet.tricks import TricksFeature


@dataclass
class TrainerRuntime:
    """Holds running trainer interfaces and feature instances."""

    osc: VRChatOSCInterface
    pishock: PiShockInterface
    whisper: WhisperInterface
    logs: SessionLogManager
    features: List[Any] = field(default_factory=list)


@dataclass
class PetRuntime:
    """Holds running pet interfaces and feature instances."""

    osc: VRChatOSCInterface
    pishock: PiShockInterface
    whisper: WhisperInterface
    logs: SessionLogManager
    features: List[Any] = field(default_factory=list)


_trainer_runtime: Optional[TrainerRuntime] = None
_pet_runtime: Optional[PetRuntime] = None
_server_interface: Optional[DummyServerInterface] = None


def _apply_feature_flags(features: List[Any], feature_flags: Dict[type, bool]) -> None:
    """Set enabled state on all known features when supported."""

    for feature in features:
        for cls, enabled in feature_flags.items():
            if isinstance(feature, cls):
                if hasattr(feature, "set_enabled"):
                    feature.set_enabled(bool(enabled))
                break


def _apply_feature_scaling(features: List[Any], scaling: Dict[str, float]) -> None:
    """Push scaling factors to all features that support runtime updates."""
    for feature in features:
        if hasattr(feature, "set_scaling"):
            feature.set_scaling(
                delay_scale=scaling.get("delay_scale", 1.0),
                cooldown_scale=scaling.get("cooldown_scale", 1.0),
                duration_scale=scaling.get("duration_scale", 1.0),
                strength_scale=scaling.get("strength_scale", 1.0),
            )


def _extract_scaling(settings: Dict[str, Any]) -> Dict[str, float]:
    """Clamp and normalise scaling values from settings dict."""
    def _safe_scale(key: str) -> float:
        try:
            value = float(settings.get(key, 1.0))
        except Exception:
            value = 1.0
        return max(0.0, min(2.0, value))

    return {
        "delay_scale": _safe_scale("delay_scale"),
        "cooldown_scale": _safe_scale("cooldown_scale"),
        "duration_scale": _safe_scale("duration_scale"),
        "strength_scale": _safe_scale("strength_scale"),
    }


def _ensure_server(role: str = "trainer") -> DummyServerInterface:
    """Create or return the shared dummy server interface."""
    global _server_interface

    if _server_interface is None:
        _server_interface = DummyServerInterface(role=role)
        _server_interface.start()
    return _server_interface


def start_server_session(session_label: str | None = None) -> dict:
    """Start a new server session (stub)."""

    server = _ensure_server()
    return server.start_session(session_label=session_label)


def join_server_session(session_id: str) -> dict:
    """Join an existing server session (stub)."""

    server = _ensure_server()
    return server.join_session(session_id=session_id)


def leave_server_session() -> dict:
    """Leave the current server session (stub)."""

    server = _ensure_server()
    return server.leave_session()


def get_server_session_details() -> dict:
    """Return current session state for UI display."""

    server = _ensure_server()
    return server.get_session_details()


def _build_trainer_interfaces(trainer_settings: dict, input_device: Optional[str]) -> TrainerRuntime:
    logs = SessionLogManager("trainer")

    osc = VRChatOSCInterface(
        log_all_events=logs.get_logger("osc_all.log").log,
        log_relevant_events=logs.get_logger("osc_relevant.log").log,
        role="trainer",
    )

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
    server = _ensure_server(role="trainer")
    try:
        server.send_settings(trainer_settings)
    except Exception:
        pass

    # Trainer runtime currently holds only interfaces; feature logic
    # now runs on the pet side.
    features: List[Any] = []
    return TrainerRuntime(osc=osc, pishock=pishock, whisper=whisper, logs=logs, features=features)


def _build_pet_interfaces(pet_settings: dict, input_device: Optional[str]) -> PetRuntime:
    logs = SessionLogManager("pet")

    osc = VRChatOSCInterface(
        log_all_events=logs.get_logger("osc_all.log").log,
        log_relevant_events=logs.get_logger("osc_relevant.log").log,
        role="pet",
    )

    pishock = PiShockInterface(
        username=pet_settings.get("pishock_username") or "",
        api_key=pet_settings.get("pishock_api_key") or "",
        role="pet",
    )

    whisper = WhisperInterface(input_device=input_device)

    osc.start()
    pishock.start()
    whisper.start()

    scaling = _extract_scaling(pet_settings)
    server = _ensure_server(role="pet")

    features: List[Any] = [
        PullFeature(osc=osc, pishock=pishock, whisper=whisper, logger=logs.get_logger("pull_feature.log")),
        PronounsFeature(osc=osc, pishock=pishock, whisper=whisper, logger=logs.get_logger("pronouns_feature.log")),
        FocusFeature(
            osc=osc,
            pishock=pishock,
            whisper=whisper,
            server=server,
            scaling=scaling,
            names=pet_settings.get("names") or [],
            logger=logs.get_logger("focus_feature.log"),
        ),
        ProximityFeature(
            osc=osc,
            pishock=pishock,
            whisper=whisper,
            server=server,
            scaling=scaling,
            names=pet_settings.get("names") or [],
            logger=logs.get_logger("proximity_feature.log"),
        ),
        TricksFeature(
            osc=osc,
            pishock=pishock,
            whisper=whisper,
            names=pet_settings.get("names") or [],
            scaling=scaling,
            logger=logs.get_logger("tricks_feature.log"),
        ),
        ScoldingFeature(
            osc=osc,
            pishock=pishock,
            whisper=whisper,
            scolding_words=pet_settings.get("scolding_words") or [],
            scaling=scaling,
            logger=logs.get_logger("scolding_feature.log"),
        ),
    ]

    _apply_feature_flags(
        features,
        {
            FocusFeature: bool(pet_settings.get("feature_focus")),
            ProximityFeature: bool(pet_settings.get("feature_proximity")),
            TricksFeature: bool(pet_settings.get("feature_tricks")),
            ScoldingFeature: bool(pet_settings.get("feature_scolding")),
            PullFeature: bool(pet_settings.get("feature_ear_tail")),
            PronounsFeature: bool(pet_settings.get("feature_pronouns")),
        },
    )
    _apply_feature_scaling(features, scaling)

    for feature in features:
        if hasattr(feature, "start"):
            feature.start()

    return PetRuntime(osc=osc, pishock=pishock, whisper=whisper, logs=logs, features=features)


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


def update_trainer_feature_states(trainer_settings: dict) -> None:
    """Update trainer feature enablement without restarting services."""

    runtime = _trainer_runtime
    if runtime is None:
        return
    # Trainer currently has no feature logic; nothing to update.
    server = _ensure_server(role="trainer")
    try:
        server.send_settings(trainer_settings)
    except Exception:
        pass


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


def update_pet_feature_states(pet_settings: dict) -> None:
    """Update pet feature enablement without restarting services."""

    runtime = _pet_runtime
    if runtime is None:
        return

    scaling = _extract_scaling(pet_settings)
    _apply_feature_scaling(runtime.features, scaling)

    _apply_feature_flags(
        runtime.features,
        {
            FocusFeature: bool(pet_settings.get("feature_focus")),
            ProximityFeature: bool(pet_settings.get("feature_proximity")),
            TricksFeature: bool(pet_settings.get("feature_tricks")),
            ScoldingFeature: bool(pet_settings.get("feature_scolding")),
            PullFeature: bool(pet_settings.get("feature_ear_tail")),
            PronounsFeature: bool(pet_settings.get("feature_pronouns")),
        },
    )


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
        "enabled": getattr(pishock, "enabled", True),
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
        "enabled": getattr(pishock, "enabled", True),
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
