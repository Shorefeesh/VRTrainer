from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment specific
    raise RuntimeError(
        "PyYAML is required to use the configuration system. "
        "Install it with `pip install pyyaml`."
    ) from exc


def _config_target_path() -> Path:
    """Return a writable config path that survives PyInstaller onefile.

    When frozen, ``__file__`` points inside the temporary extraction
    directory, so writes would disappear between runs. Using the
    executable's location keeps the config alongside the bundled app.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name("config.yaml")

    return Path(__file__).resolve().with_name("config.yaml")


CONFIG_PATH = _config_target_path()


def _default_config() -> Dict[str, Any]:
    """Return a fresh default configuration structure."""
    return {
        "settings": {
            "input_device": None,
        },
        "trainer": {
            "active_profile": None,
            "profiles": {},
        },
        "pet": {},
    }


def load_config(path: Path | None = None) -> Dict[str, Any]:
    """Load configuration from YAML, falling back to defaults if missing/empty."""
    target = Path(path) if path is not None else CONFIG_PATH

    if not target.exists():
        return _default_config()

    with target.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    config = _default_config()

    # Shallow merge on top-level sections to keep future compatibility simple.
    for key, value in raw.items():
        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
            config[key].update(value)
        else:
            config[key] = value

    return config


def save_config(config: Dict[str, Any], path: Path | None = None) -> None:
    """Persist configuration to YAML."""
    target = Path(path) if path is not None else CONFIG_PATH
    # Make sure parent exists in case the project is relocated.
    target.parent.mkdir(parents=True, exist_ok=True)

    # Work with a copy to avoid accidental mutation while dumping.
    data = deepcopy(config)

    with target.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            data,
            fh,
            default_flow_style=False,
            sort_keys=False,
        )
