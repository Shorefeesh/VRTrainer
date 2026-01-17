#!/usr/bin/env python
"""
Build a standalone VRTrainer executable with PyInstaller.

Usage:
    python build_exe.py

The script assumes PyInstaller is installed in the active environment.
It bundles the Tkinter GUI, configuration file, and the `models/` folder
so Whisper downloads remain co-located with the binary.
"""

from __future__ import annotations

import os
from pathlib import Path

import PyInstaller.__main__


def _datas(project_root: Path) -> list[str]:
    """Return --add-data arguments with correct path separator per OS."""
    sep = ";" if os.name == "nt" else ":"
    return [
        f"{project_root / 'config.yaml'}{sep}.",
        f"{project_root / 'models'}{sep}models",
    ]


def main() -> None:
    root = Path(__file__).resolve().parent

    args = [
        "--noconfirm",
        "--clean",
        "--onefile",  # single bundled executable
        "--windowed",  # hide console on Windows; no effect on Linux
        "--name=VRTrainer",
        *[f"--add-data={data}" for data in _datas(root)],
        # Optional hidden imports; PyInstaller usually finds these, but the
        # list keeps the build stable across environments.
        "--hidden-import=sounddevice",
        "--hidden-import=faster_whisper",
        "--hidden-import=pythonosc",
        "--hidden-import=pishock",
        "--hidden-import=yaml",
        "--hidden-import=matplotlib",
        "--hidden-import=requests",
        "--hidden-import=websocket_client",
        str(root / "main.py"),
    ]

    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
