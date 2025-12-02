import tkinter as tk
from tkinter import ttk

from .shared import LabeledEntry, LabeledCheckbutton, StatusIndicator


class PetTab(ttk.Frame):
    """Pet tab UI."""

    def __init__(self, master, on_start=None, **kwargs) -> None:
        super().__init__(master, **kwargs)

        self.on_start = on_start
        self._is_running = False

        self._build_pishock_section()
        self._build_features_section()
        self._build_controls_section()

        for col in range(2):
            self.columnconfigure(col, weight=1)

    def _build_pishock_section(self) -> None:
        frame = ttk.LabelFrame(self, text="PiShock credentials")
        frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        frame.columnconfigure(0, weight=1)

        self.pishock_username = LabeledEntry(frame, "Username")
        self.pishock_username.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self.pishock_api_key = LabeledEntry(frame, "API key", show="*")
        self.pishock_api_key.grid(row=1, column=0, sticky="ew")

    def _build_features_section(self) -> None:
        frame = ttk.LabelFrame(self, text="Features")
        frame.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)

        self.feature_ear_tail = LabeledCheckbutton(frame, "Ear/Tail pull")
        self.feature_pronouns = LabeledCheckbutton(frame, "Pronouns")

        self.feature_ear_tail.grid(row=0, column=0, sticky="w")
        self.feature_pronouns.grid(row=1, column=0, sticky="w")

    def _build_controls_section(self) -> None:
        control_frame = ttk.Frame(self)
        control_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 12))
        control_frame.columnconfigure(0, weight=1)

        self.start_button = ttk.Button(control_frame, text="Start", command=self._toggle_start)
        self.start_button.grid(row=0, column=0, sticky="w")

        status_frame = ttk.LabelFrame(control_frame, text="Running status")
        status_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        status_frame.columnconfigure(0, weight=1)

        self.running_status = StatusIndicator(status_frame, "Pet")
        self.running_status.grid(row=0, column=0, sticky="w", padx=6, pady=6)

    # Public helpers -----------------------------------------------------
    def collect_settings(self) -> dict:
        """Collect the current pet settings into a dictionary."""
        return {
            "pishock_username": self.pishock_username.variable.get(),
            "pishock_api_key": self.pishock_api_key.variable.get(),
            "feature_ear_tail": self.feature_ear_tail.variable.get(),
            "feature_pronouns": self.feature_pronouns.variable.get(),
        }

    def set_running_state(self, running: bool) -> None:
        self._is_running = running
        self.start_button.configure(text="Stop" if running else "Start")
        if running:
            self.running_status.set_status("Running", "green")
        else:
            self.running_status.set_status("Stopped", "grey")

    def _toggle_start(self) -> None:
        new_state = not self._is_running
        self.set_running_state(new_state)
        if self.on_start is not None:
            self.on_start(new_state)
