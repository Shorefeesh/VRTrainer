from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import threading
from typing import Dict, Iterable, List


@dataclass
class LogFile:
    """Thread-safe append-only log file with timestamped entries."""

    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {message}\n"

        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
        except Exception:
            # Logging should never break the main application flow.
            return


class SessionLogManager:
    """Factory for per-session log files under ``logs/``.

    Each session gets its own subdirectory named ``{label}-{timestamp}`` and can
    vend multiple log files via :meth:`get_logger`.
    """

    def __init__(self, label: str) -> None:
        base_dir = get_logs_root()
        base_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_dir = base_dir / f"{label}-{timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._loggers: Dict[str, LogFile] = {}

    def get_logger(self, filename: str) -> LogFile:
        if filename not in self._loggers:
            self._loggers[filename] = LogFile(self.session_dir / filename)
        return self._loggers[filename]


def get_logs_root() -> Path:
    """Return the root logs directory path."""

    return Path(__file__).resolve().parent.parent / "logs"


def list_session_directories(labels: Iterable[str] | None = None) -> List[Path]:
    """Return sorted session directories filtered by optional labels.

    Args:
        labels: Optional iterable of session labels (e.g., ``{"trainer", "pet"}``).
            If provided, only sessions whose directory names start with one of the
            labels will be returned.
    """

    base_dir = get_logs_root()
    if not base_dir.exists():
        return []

    label_prefixes = None if labels is None else {f"{label}-" for label in labels}
    sessions = []
    for path in base_dir.iterdir():
        if not path.is_dir():
            continue
        if label_prefixes is not None and not any(path.name.startswith(prefix) for prefix in label_prefixes):
            continue
        sessions.append(path)

    return sorted(sessions, key=lambda p: p.name, reverse=True)
