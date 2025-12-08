from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import os
import logging
import time

from interfaces.pishock import PiShockInterface
from interfaces.vrchatosc import VRChatOSCInterface
from interfaces.whisper import WhisperInterface
from interfaces.server import RemoteServerInterface
from logic.logging_utils import SessionLogManager
from logic.pet.focus import FocusFeature
from logic.pet.wordgame import WordFeature
from logic.pet.proximity import ProximityFeature
from logic.pet.pull import PullFeature
from logic.pet.scolding import ScoldingFeature
from logic.pet.tricks import TricksFeature
from logic.trainer.focus import TrainerFocusFeature
from logic.trainer.proximity import TrainerProximityFeature
from logic.trainer.scolding import TrainerScoldingFeature
from logic.trainer.tricks import TrainerTricksFeature


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
_server_interface: Optional[RemoteServerInterface] = None
_logger = logging.getLogger(__name__)
_status_cache: Dict[str, Dict[str, Any]] = {"trainer": {}, "pet": {}}
# Map pet client UUIDs to the trainer profile name currently assigned in-session.
_pet_profile_assignments: Dict[str, str] = {}
# Cache the last config payload sent per pet so we can replay after reconnects.
_pet_profile_payloads: Dict[str, Dict[str, Any]] = {}


def _maybe_publish_status(role: str, status: Dict[str, str]) -> None:
    """Push runtime status to the shared session (if connected).

    Uses a small cache to avoid hammering the server with identical payloads.
    """

    if _server_interface is None:
        return

    cache = _status_cache.setdefault(role, {})
    last_payload = cache.get("payload")
    last_ts = float(cache.get("ts", 0.0))
    now = time.time()

    if status == last_payload and now - last_ts < 5.0:
        return

    try:
        _server_interface.send_status({"kind": "status", **status})
        cache["payload"] = dict(status)
        cache["ts"] = now
    except Exception:
        pass


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


def _create_server(role: str) -> RemoteServerInterface:
    """Instantiate the configured server interface (remote if available)."""
    base_url = os.getenv("VRTRAINER_SERVER_URL", "").strip()

    # Prefer the hosted API when a URL is configured (default points to production).
    target = base_url or "https://vrtrainer.online"
    server = RemoteServerInterface(base_url=target, role=role)
    server.start()
    if server.is_connected:
        _logger.info("Connected to remote server at %s", target)
    else:
        _logger.warning("Remote server %s unreachable", target)
        server.record_local_event("Server unreachable; working offline")

    return server




def _ensure_server(role: str | None = None) -> RemoteServerInterface:
    """Create or return the shared server interface (remote or dummy)."""
    global _server_interface

    if _server_interface is None:
        _server_interface = _create_server(role or "trainer")
    elif role is not None:
        _server_interface.set_role(role)
    return _server_interface


def _send_profile_config_to_pet(pet_client_id: str | list[str], settings: Dict[str, Any]) -> None:
    """Send a trainer profile payload to one or more pet clients via the server."""

    if not pet_client_id or not settings:
        return

    server = _ensure_server(role="trainer")
    try:
        server.send_config(settings, target_client=pet_client_id)
    except Exception:
        # Fail-soft: network hiccups should not crash the runtime.
        pass


def _replay_profile_configs() -> None:
    """Resend cached profile payloads to currently assigned pets."""

    if not _pet_profile_payloads:
        return

    server = _ensure_server(role="trainer")
    for pet_id, payload in list(_pet_profile_payloads.items()):
        try:
            server.send_config(payload, target_client=pet_id)
        except Exception:
            continue


def _prune_missing_pet_assignments(session_pets: List[Dict[str, Any]]) -> None:
    """Drop assignments for pets that are no longer present in the session."""

    active_ids = {p.get("client_uuid") for p in session_pets if p.get("client_uuid")}
    for pet_id in list(_pet_profile_assignments.keys()):
        if pet_id not in active_ids:
            _pet_profile_assignments.pop(pet_id, None)
            _pet_profile_payloads.pop(pet_id, None)


def assign_profile_to_pet(pet_client_id: str, profile_name: str | None, profile_settings: Dict[str, Any] | None) -> None:
    """Record a per-pet profile selection and push it to the pet."""

    if not pet_client_id:
        return

    if not profile_name:
        _pet_profile_assignments.pop(pet_client_id, None)
        _pet_profile_payloads.pop(pet_client_id, None)
        return

    _pet_profile_assignments[pet_client_id] = profile_name
    if profile_settings:
        _pet_profile_payloads[pet_client_id] = dict(profile_settings)
        _send_profile_config_to_pet(pet_client_id, profile_settings)


def notify_profile_updated(settings: Dict[str, Any]) -> None:
    """Propagate updates to any pets currently using the edited profile."""

    profile_name = settings.get("profile") or ""
    if not profile_name:
        return

    targets = [pid for pid, prof in _pet_profile_assignments.items() if prof == profile_name]
    if not targets:
        return

    payload = dict(settings)
    for pet_id in targets:
        _pet_profile_payloads[pet_id] = payload

    _send_profile_config_to_pet(targets, payload)


def rename_profile_assignment(old_name: str, new_name: str) -> None:
    """Keep in-session assignments in sync when a profile is renamed."""

    if not old_name or not new_name or old_name == new_name:
        return

    for pet_id, prof in list(_pet_profile_assignments.items()):
        if prof == old_name:
            _pet_profile_assignments[pet_id] = new_name
            payload = _pet_profile_payloads.get(pet_id)
            if isinstance(payload, dict):
                payload["profile"] = new_name
                _send_profile_config_to_pet(pet_id, payload)


def remove_profile_assignments(profile_name: str) -> None:
    """Clear any assignments that reference a profile that was deleted."""

    for pet_id, prof in list(_pet_profile_assignments.items()):
        if prof == profile_name:
            _pet_profile_assignments.pop(pet_id, None)
            _pet_profile_payloads.pop(pet_id, None)


def set_server_username(username: str | None) -> dict:
    """Update the username used for server interactions."""

    server = _ensure_server()
    if username is not None:
        server.set_username(username)
    return server.get_session_details()


def get_server_username() -> str:
    """Return the username currently configured for server interactions."""

    server = _server_interface
    if server is None:
        return ""
    return getattr(server, "_username", "") or ""


def start_server_session(
    session_label: str | None = None,
    *,
    username: str | None = None,
    role: str = "trainer",
) -> dict:
    """Start a new server session (stub)."""

    server = _ensure_server(role)
    if username is not None:
        server.set_username(username)
    try:
        details = server.start_session(session_label=session_label)
    except Exception as exc:
        _logger.warning("start_server_session failed: %s", exc)
        server.record_local_event(f"start session failed: {exc}")
        details = server.get_session_details()

    _pet_profile_assignments.clear()
    _pet_profile_payloads.clear()
    return details


def join_server_session(session_id: str, *, username: str | None = None, role: str = "trainer") -> dict:
    """Join an existing server session (stub)."""

    server = _ensure_server(role)
    if username is not None:
        server.set_username(username)
    try:
        details = server.join_session(session_id=session_id)
    except Exception as exc:
        _logger.warning("join_server_session failed: %s", exc)
        server.record_local_event(f"join session failed: {exc}")
        details = server.get_session_details()

    _pet_profile_assignments.clear()
    _pet_profile_payloads.clear()
    return details


def leave_server_session() -> dict:
    """Leave the current server session (stub)."""

    server = _ensure_server()
    try:
        details = server.leave_session()
    except Exception as exc:
        _logger.warning("leave_server_session failed: %s", exc)
        server.record_local_event(f"leave session failed: {exc}")
        details = server.get_session_details()

    _pet_profile_assignments.clear()
    _pet_profile_payloads.clear()
    return details


def reconnect_server(role: str | None = None) -> dict:
    """Retry server health check and return updated details."""

    global _server_interface

    if _server_interface is None:
        _server_interface = _create_server(role or "trainer")
    else:
        if role is not None:
            _server_interface.set_role(role)
        _server_interface.start()

    return _server_interface.get_session_details()


def get_server_session_details() -> dict:
    """Return current session state for UI display."""

    server = _ensure_server()
    details = server.get_session_details()

    if not details.get("session_id"):
        _pet_profile_assignments.clear()
        _pet_profile_payloads.clear()
        return details

    session_users = details.get("session_users") or []
    formatted_users: List[Dict[str, Any]] = []
    for user in session_users:
        role_raw = (user.get("role") or "").lower()
        role = "trainer" if role_raw == "leader" else "pet" if role_raw == "follower" else role_raw
        client_uuid = str(user.get("client_uuid") or user.get("id") or "")
        last_status = user.get("last_status") or {}
        username = user.get("username") or last_status.get("username") or ""
        label = username or (client_uuid[:8] if client_uuid else "(unknown)")

        formatted_users.append(
            {
                "client_uuid": client_uuid,
                "role": role,
                "last_status": last_status,
                "label": label,
            }
        )

    session_pets = [u for u in formatted_users if u.get("role") == "pet"]
    _prune_missing_pet_assignments(session_pets)

    details["session_participants"] = formatted_users
    details["session_pets"] = session_pets
    details["pet_profile_assignments"] = dict(_pet_profile_assignments)
    return details


def _build_trainer_interfaces(trainer_settings: dict, input_device: Optional[str]) -> TrainerRuntime:
    logs = SessionLogManager("trainer")

    osc = VRChatOSCInterface(
        log_all_events=logs.get_logger("osc_all.log").log,
        log_relevant_events=logs.get_logger("osc_relevant.log").log,
        role="trainer",
    )

    # Trainer mode keeps PiShock disabled; credentials are no longer collected on the trainer tab.
    pishock = PiShockInterface(username="", api_key="", role="trainer")

    whisper = WhisperInterface(input_device=input_device)

    # Start all interfaces before wiring features.
    osc.start()
    pishock.start()
    whisper.start()
    server = _ensure_server(role="trainer")

    features: List[Any] = [
        TrainerFocusFeature(
            whisper=whisper,
            server=server,
            osc=osc,
            names=trainer_settings.get("names") or [],
            logger=logs.get_logger("trainer_focus_feature.log"),
        ),
        TrainerProximityFeature(
            whisper=whisper,
            server=server,
            osc=osc,
            names=trainer_settings.get("names") or [],
            logger=logs.get_logger("trainer_proximity_feature.log"),
        ),
        TrainerTricksFeature(
            whisper=whisper,
            server=server,
            osc=osc,
            names=trainer_settings.get("names") or [],
            logger=logs.get_logger("trainer_tricks_feature.log"),
        ),
        TrainerScoldingFeature(
            whisper=whisper,
            server=server,
            osc=osc,
            scolding_words=trainer_settings.get("scolding_words") or [],
            logger=logs.get_logger("trainer_scolding_feature.log"),
        ),
    ]

    _apply_feature_flags(
        features,
        {
            TrainerFocusFeature: bool(trainer_settings.get("feature_focus")),
            TrainerProximityFeature: bool(trainer_settings.get("feature_proximity")),
            TrainerTricksFeature: bool(trainer_settings.get("feature_tricks")),
            TrainerScoldingFeature: bool(trainer_settings.get("feature_scolding")),
        },
    )

    for feature in features:
        if hasattr(feature, "start"):
            feature.start()

    _replay_profile_configs()

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

    server = _ensure_server(role="pet")

    features: List[Any] = [
        PullFeature(osc=osc, pishock=pishock, whisper=whisper, server=server, logger=logs.get_logger("pull_feature.log")),
        WordFeature(osc=osc, pishock=pishock, whisper=whisper, server=server, logger=logs.get_logger("pronouns_feature.log")),
        FocusFeature(
            osc=osc,
            pishock=pishock,
            server=server,
            logger=logs.get_logger("focus_feature.log"),
        ),
        ProximityFeature(
            osc=osc,
            pishock=pishock,
            server=server,
            logger=logs.get_logger("proximity_feature.log"),
        ),
        TricksFeature(
            osc=osc,
            pishock=pishock,
            server=server,
            logger=logs.get_logger("tricks_feature.log"),
        ),
        ScoldingFeature(
            osc=osc,
            pishock=pishock,
            server=server,
            logger=logs.get_logger("scolding_feature.log"),
        ),
    ]

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

    _apply_feature_flags(
        runtime.features,
        {
            TrainerFocusFeature: bool(trainer_settings.get("feature_focus")),
            TrainerProximityFeature: bool(trainer_settings.get("feature_proximity")),
            TrainerTricksFeature: bool(trainer_settings.get("feature_tricks")),
            TrainerScoldingFeature: bool(trainer_settings.get("feature_scolding")),
        },
    )


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
    # Pet runtime feature states are now driven exclusively by the
    # trainer configs delivered via the server. This method remains as a
    # no-op to preserve API compatibility with the UI layer.
    return None


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


def get_trainer_whisper_backend() -> str:
    runtime = _trainer_runtime
    if runtime is None:
        return "Stopped"
    return runtime.whisper.get_backend_summary()


def get_pet_whisper_backend() -> str:
    runtime = _pet_runtime
    if runtime is None:
        return "Stopped"
    return runtime.whisper.get_backend_summary()


def publish_runtime_status(role: str, status: Dict[str, str]) -> None:
    """Share the latest runtime status with the active session."""

    if role not in {"trainer", "pet"}:
        return
    _maybe_publish_status(role, status)
