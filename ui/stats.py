from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Dict, List, Tuple
import tkinter as tk
from tkinter import ttk

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from logic.logging_utils import list_session_directories

_LOG_FILES: Dict[str, str] = {
    "focus": "focus_feature.log",
    "proximity": "proximity_feature.log",
    "tricks": "tricks_feature.log",
    "scolding": "scolding_feature.log",
    "pull": "pull_feature.log",
    "depth": "depth_feature.log",
    "pronouns": "pronouns_feature.log",
}

_LOG_PATTERN = re.compile(r"^\[(?P<ts>[^\]]+)\]\s*(?P<body>.*)$")


class StatsTab(ttk.Frame):
    """Tab that visualises session feature logs on a shared timeline."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)

        control_frame = ttk.Frame(self)
        control_frame.pack(fill="x", pady=8, padx=8)

        ttk.Label(control_frame, text="Session:").pack(side="left", padx=(0, 6))
        self.session_var = tk.StringVar()
        self.session_combo = ttk.Combobox(control_frame, textvariable=self.session_var, state="readonly", width=40)
        self.session_combo.pack(side="left", padx=(0, 6))
        self.session_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_selected_session())

        refresh_btn = ttk.Button(control_frame, text="Refresh", command=self._refresh_sessions)
        refresh_btn.pack(side="left")

        self.message_var = tk.StringVar(value="Select a session to view timeline statistics.")
        ttk.Label(self, textvariable=self.message_var, foreground="gray").pack(anchor="w", padx=10)

        self.figure = Figure(figsize=(8, 4), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill="both", expand=True, padx=8, pady=8)

        self._sessions: Dict[str, Path] = {}
        self._refresh_sessions()

    # Session handling -------------------------------------------------
    def _refresh_sessions(self) -> None:
        """Reload the list of log sessions from disk."""

        sessions = list_session_directories(labels={"trainer", "pet"})
        self._sessions = {session.name: session for session in sessions}

        current = self.session_var.get()
        names = list(self._sessions.keys())
        self.session_combo["values"] = names

        if current in self._sessions:
            self.session_combo.set(current)
        elif names:
            self.session_combo.set(names[0])
            current = names[0]
        else:
            self.session_combo.set("")
            current = ""

        if current:
            self._render_selected_session()
        else:
            self._clear_plot("No sessions found. Start a trainer or pet run to record logs.")

    def _render_selected_session(self) -> None:
        session_name = self.session_var.get()
        session_path = self._sessions.get(session_name)
        if not session_path:
            self._clear_plot("Select a session to view timeline statistics.")
            return

        events = _load_session_events(session_path)
        if not events:
            self._clear_plot("No timeline events found in the selected session.")
            return

        self._plot_events(events, session_name)

    # Plotting ---------------------------------------------------------
    def _plot_events(self, events: List[Dict[str, object]], session_name: str) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        focus_points: List[Tuple[datetime, float]] = []
        proximity_points: List[Tuple[datetime, float]] = []
        markers: List[Tuple[datetime, float, str, str]] = []  # timestamp, y, label, color

        for event in events:
            timestamp = event["timestamp"]
            feature = str(event.get("feature", ""))
            event_name = str(event.get("event", ""))

            if event_name == "sample" and feature == "focus":
                value = float(event.get("meter", 0.0))
                focus_points.append((timestamp, value))
            elif event_name == "sample" and feature == "proximity":
                value = float(event.get("value", event.get("proximity", 0.0)))
                proximity_points.append((timestamp, value))
            elif event_name:
                y_value = _choose_marker_value(event)
                markers.append((timestamp, y_value, _format_marker_label(event), _marker_color(event_name)))

        if focus_points:
            times, values = zip(*focus_points)
            ax.plot(times, values, label="Focus", color="#4c6ef5")

        if proximity_points:
            times, values = zip(*proximity_points)
            ax.plot(times, values, label="Proximity", color="#0ca678")

        for ts, y, label, color in markers:
            ax.scatter(ts, y, color=color, s=30, zorder=3)
            ax.annotate(label, (mdates.date2num(ts), y), textcoords="offset points", xytext=(4, 6), fontsize=8, color=color)

        if focus_points or proximity_points:
            y_min = min([val for _, val in focus_points + proximity_points] + [0.0])
            y_max = max([val for _, val in focus_points + proximity_points] + [1.0])
            ax.set_ylim(y_min - 0.05, y_max + 0.2)
        else:
            ax.set_ylim(-0.1, 1.1)

        ax.set_title(f"Timeline: {session_name}")
        ax.set_ylabel("Value")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax.set_xlabel("Time")
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)

        if focus_points or proximity_points:
            ax.legend()

        self.figure.autofmt_xdate()
        self.canvas.draw()
        self.message_var.set(f"Loaded {len(events)} events from {session_name}.")

    def _clear_plot(self, message: str) -> None:
        self.figure.clear()
        self.canvas.draw()
        self.message_var.set(message)


# Parsing helpers ------------------------------------------------------

def _load_session_events(session_dir: Path) -> List[Dict[str, object]]:
    events: List[Dict[str, object]] = []

    for feature, filename in _LOG_FILES.items():
        path = session_dir / filename
        if not path.exists():
            continue

        for line in path.read_text(encoding="utf-8").splitlines():
            event = _parse_log_line(line.strip())
            if event is None:
                continue
            if "feature" not in event:
                event["feature"] = feature
            events.append(event)

    events.sort(key=lambda e: e.get("timestamp", datetime.min))
    return events


def _parse_log_line(line: str) -> Dict[str, object] | None:
    if not line:
        return None

    match = _LOG_PATTERN.match(line)
    if not match:
        return None

    ts_text = match.group("ts")
    body = match.group("body")

    try:
        timestamp = datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None

    event: Dict[str, object] = {"timestamp": timestamp, "text": body}
    for token in body.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        event[key] = _coerce_value(value)

    return event


def _coerce_value(value: str) -> object:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"

    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _format_marker_label(event: Dict[str, object]) -> str:
    event_name = str(event.get("event", "")).replace("_", " ")
    feature = event.get("feature", "")
    name = event.get("name")
    parts = [event_name.title()]
    if feature:
        parts.append(f"[{feature}]")
    if name:
        parts.append(str(name))
    return " ".join(parts)


def _marker_color(event_name: str) -> str:
    if event_name == "shock":
        return "#fa5252"
    if event_name == "command_start":
        return "#f59f00"
    if event_name == "command_success":
        return "#12b886"
    return "#495057"


def _choose_marker_value(event: Dict[str, object]) -> float:
    for key in ("meter", "value", "proximity", "stretch"):
        if key in event:
            try:
                return float(event[key])
            except (TypeError, ValueError):
                continue
    return 1.05


__all__ = ["StatsTab"]
