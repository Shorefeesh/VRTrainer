from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment specific
    raise RuntimeError(
        "PyYAML is required to use the configuration system. "
        "Install it with `pip install pyyaml`."
    ) from exc


CONFIG_PATH = Path(__file__).with_name("config.yaml")


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
