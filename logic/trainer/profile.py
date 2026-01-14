from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


TRAINER_SETTINGS_KEYS = [
    "profile",
    "feature_focus",
    "feature_proximity",
    "feature_tricks",
    "feature_scolding",
    "feature_forbidden_words",
    "feature_ear_tail",
    "word_game",
    "delay_scale",
    "cooldown_scale",
    "duration_scale",
    "strength_scale",
    "names",
    "command_words",
    "scolding_words",
    "forbidden_words",
]


def ensure_trainer_section(config: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure the trainer section exists on the config object."""
    trainer = config.setdefault("trainer", {})
    trainer.setdefault("active_profile", None)
    trainer.setdefault("profiles", {})
    return trainer


def list_profile_names(config: Dict[str, Any]) -> List[str]:
    """Return all known trainer profile names."""
    trainer = ensure_trainer_section(config)
    return sorted(trainer["profiles"].keys())


def get_active_profile_name(config: Dict[str, Any]) -> str | None:
    """Return the currently active trainer profile name, if any."""
    trainer = ensure_trainer_section(config)
    return trainer.get("active_profile")


def set_active_profile_name(config: Dict[str, Any], name: str | None) -> None:
    """Set the active trainer profile name."""
    trainer = ensure_trainer_section(config)
    trainer["active_profile"] = name


def default_profile_settings(profile_name: str) -> Dict[str, Any]:
    """Default settings for a new trainer profile."""
    return {
        "profile": profile_name,
        "feature_focus": False,
        "feature_proximity": False,
        "feature_tricks": False,
        "feature_scolding": False,
        "feature_forbidden_words": False,
        "feature_ear_tail": False,
        "word_game": "None",
        "delay_scale": 1.0,
        "cooldown_scale": 1.0,
        "duration_scale": 1.0,
        "strength_scale": 1.0,
        "names": [],
        "command_words": [],
        "scolding_words": [],
        "forbidden_words": [],
    }


def get_profile(config: Dict[str, Any], name: str) -> Dict[str, Any] | None:
    """Retrieve a copy of a single profile's settings."""
    trainer = ensure_trainer_section(config)
    profile = trainer["profiles"].get(name)
    return deepcopy(profile) if profile is not None else None


def update_profile_from_settings(config: Dict[str, Any], settings: Dict[str, Any]) -> None:
    """Upsert profile data in config based on settings dict from the UI.

    The `settings` dict is expected to contain the keys from TRAINER_SETTINGS_KEYS.
    """
    trainer = ensure_trainer_section(config)
    profile_name = settings.get("profile") or ""
    if not profile_name:
        return

    existing = trainer["profiles"].get(profile_name) or default_profile_settings(profile_name)

    for key in TRAINER_SETTINGS_KEYS:
        if key in settings:
            existing[key] = settings[key]

    trainer["profiles"][profile_name] = existing
    trainer["active_profile"] = profile_name


def rename_profile(config: Dict[str, Any], old_name: str, new_name: str) -> bool:
    """Rename a profile in-place, keeping its settings.

    Returns True if the rename was applied, False if the old profile
    didn't exist or the new name is already taken.
    """
    trainer = ensure_trainer_section(config)
    profiles = trainer["profiles"]

    if old_name not in profiles or new_name in profiles:
        return False

    profiles[new_name] = profiles.pop(old_name)
    profiles[new_name]["profile"] = new_name

    if trainer.get("active_profile") == old_name:
        trainer["active_profile"] = new_name

    return True


def delete_profile(config: Dict[str, Any], name: str) -> bool:
    """Delete a profile from the configuration.

    Returns True if the profile was removed, False if it did not exist.
    """
    trainer = ensure_trainer_section(config)
    profiles = trainer["profiles"]

    if name not in profiles:
        return False

    profiles.pop(name)

    if trainer.get("active_profile") == name:
        trainer["active_profile"] = None

    return True
