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
from logic.feature import FeatureContext, build_features_for_role
from logic.logging_utils import SessionLogManager


@dataclass
class Runtime:
    """Holds running trainer interfaces and feature instances."""

    osc: VRChatOSCInterface
    pishock: PiShockInterface
    whisper: WhisperInterface
    logs: SessionLogManager
    features: List[Any] = field(default_factory=list)


_runtime: Optional[Runtime] = None
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


def get_assigned_pet_configs() -> Dict[str, Dict[str, Any]]:
    """Return a shallow copy of current per-pet profile payloads.

    Used by trainer-side features to route commands per pet using that pet's
    assigned configuration (names, words, feature flags, etc.).
    """

    return {pid: dict(payload) for pid, payload in _pet_profile_payloads.items()}


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


def _build_interfaces(role: str, settings: dict, input_device: Optional[str]) -> Runtime:
    logs = SessionLogManager(role)

    osc = VRChatOSCInterface(
        log_relevant_events=logs.get_logger("osc_relevant.log").log,
        role=role,
    )

    if role == "trainer":
        pishock = PiShockInterface(username="", api_key="", share_code="", role=role, osc=osc)
    else:
        pishock = PiShockInterface(
            username=settings.get("pishock_username") or "",
            api_key=settings.get("pishock_api_key") or "",
            share_code=settings.get("pishock_share_code") or "",
            role=role,
            osc=osc,
        )

    whisper = WhisperInterface(input_device=input_device)

    # Start all interfaces before wiring features.
    osc.start()
    pishock.start()
    whisper.start()
    server = _ensure_server(role=role)

    if role == "trainer":
        context = FeatureContext(
            role=role,
            osc=osc,
            pishock=pishock,
            whisper=whisper,
            server=server,
            log_manager=logs,
            config_provider=get_assigned_pet_configs,
        )
    else:
        context = FeatureContext(
            role=role,
            osc=osc,
            pishock=pishock,
            whisper=whisper,
            server=server,
            log_manager=logs,
        )

    features: List[Any] = build_features_for_role(role, context)

    for feature in features:
        if hasattr(feature, "start"):
            feature.start()

    _replay_profile_configs()

    return Runtime(osc=osc, pishock=pishock, whisper=whisper, logs=logs, features=features)


def start_runtime(role: str, trainer_settings: dict, input_device: Optional[str]) -> None:
    """Launch all interfaces and construct feature instances for enabled features.

    This function is intended to be called when joining a Session.
    """
    global _runtime

    # If already running, stop the previous runtime first.
    if _runtime is not None:
        stop_runtime()

    _runtime = _build_interfaces(role, trainer_settings, input_device)


def stop_runtime() -> None:
    """Tear down running trainer interfaces and features, if any."""
    global _runtime

    runtime = _runtime
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

    _runtime = None


def is_running() -> bool:
    """Return True if trainer services are currently active."""
    return _runtime is not None


def get_osc_status() -> Optional[Dict[str, Any]]:
    """Return a snapshot of pet OSC diagnostics, if running."""
    if _runtime is None:
        return None
    return _runtime.osc.get_status_snapshot()


def get_pishock_status() -> Optional[Dict[str, Any]]:
    """Return a snapshot of pet PiShock status, if running."""
    if _runtime is None:
        return None

    pishock = _runtime.pishock
    return {
        "enabled": getattr(pishock, "enabled", True),
        "connected": pishock.is_connected,
        "has_credentials": bool(getattr(pishock, "username", "") and getattr(pishock, "api_key", "")),
    }


def get_whisper_log_text() -> str:
    """Return new Whisper transcript text for the UI log."""
    if _runtime is None:
        return ""

    return _runtime.whisper.get_new_text("ui_log")


def get_whisper_backend() -> str:
    if _runtime is None:
        return "Stopped"
    return _runtime.whisper.get_backend_summary()


def publish_runtime_status(role: str, status: Dict[str, str]) -> None:
    """Share the latest runtime status with the active session."""

    _maybe_publish_status(role, status)
