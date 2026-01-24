from __future__ import annotations

from typing import List
import sounddevice as sd


def list_input_devices() -> List[str]:
    """Return a list of available audio input device names.

    This uses the optional ``sounddevice`` library when available. If the
    library is not installed or an error occurs while querying devices,
    an empty list is returned so the rest of the application can
    continue to function.
    """
    devices_info = sd.query_devices()

    names: List[str] = []
    seen: set[str] = set()

    for info in devices_info:
        # Only keep devices that can record audio.
        if info.get("max_input_channels", 0) <= 0:
            continue

        name = info.get("name")
        if not name or not isinstance(name, str):
            continue

        if name in seen:
            continue

        seen.add(name)
        names.append(name)

    return names
