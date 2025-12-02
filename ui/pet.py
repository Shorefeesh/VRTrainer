import tkinter as tk
from tkinter import ttk

from .shared import (
    ScrollableFrame,
    create_features_frame,
    create_pishock_credentials_frame,
    create_running_status_frame,
)

class PetTab(ScrollableFrame):
    """Pet tab UI."""

    def __init__(self, master, on_settings_change=None, on_start=None, **kwargs) -> None:
        super().__init__(master, **kwargs)

        self.on_settings_change = on_settings_change
        self.on_start = on_start
        self._suppress_callbacks = False
        self._is_running = False

        self._build_pishock_section()
        self._build_features_section()
        self._build_controls_section()

        self.container.columnconfigure(0, weight=1)

    def _build_pishock_section(self) -> None:
        frame, self.pishock_username, self.pishock_api_key = create_pishock_credentials_frame(self.container)
        frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        self.pishock_username.variable.trace_add("write", self._on_any_setting_changed)
        self.pishock_api_key.variable.trace_add("write", self._on_any_setting_changed)

    def _build_features_section(self) -> None:
        frame, features = create_features_frame(self.container, ["Ear/Tail pull", "Pronouns"])
        frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)

        self.feature_ear_tail, self.feature_pronouns = features

        self.feature_ear_tail.variable.trace_add("write", self._on_any_setting_changed)
        self.feature_pronouns.variable.trace_add("write", self._on_any_setting_changed)

    def _build_controls_section(self) -> None:
        control_frame = ttk.Frame(self.container)
        control_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        control_frame.columnconfigure(0, weight=1)

        self.start_button = ttk.Button(control_frame, text="Start", command=self._toggle_start)
        self.start_button.grid(row=0, column=0, sticky="w")

        (
            status_frame,
            self.osc_status,
            self.pishock_status,
            self.whisper_status,
            self.whisper_log,
            self.active_features_status,
        ) = create_running_status_frame(control_frame)

        status_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

    # Public helpers -----------------------------------------------------
    def collect_settings(self) -> dict:
        """Collect the current pet settings into a dictionary."""
        return {
            "pishock_username": self.pishock_username.variable.get(),
            "pishock_api_key": self.pishock_api_key.variable.get(),
            "feature_ear_tail": self.feature_ear_tail.variable.get(),
            "feature_pronouns": self.feature_pronouns.variable.get(),
        }

    def apply_settings(self, settings: dict | None) -> None:
        """Apply stored pet settings without triggering callbacks."""
        self._suppress_callbacks = True
        try:
            if not settings:
                self.pishock_username.variable.set("")
                self.pishock_api_key.variable.set("")
                self.feature_ear_tail.variable.set(False)
                self.feature_pronouns.variable.set(False)
            else:
                self.pishock_username.variable.set(settings.get("pishock_username", ""))
                self.pishock_api_key.variable.set(settings.get("pishock_api_key", ""))
                self.feature_ear_tail.variable.set(bool(settings.get("feature_ear_tail")))
                self.feature_pronouns.variable.set(bool(settings.get("feature_pronouns")))
        finally:
            self._suppress_callbacks = False

    def set_running_state(self, running: bool) -> None:
        self._is_running = running
        self.start_button.configure(text="Stop" if running else "Start")
        if running:
            self.osc_status.set_status("Receiving parameters", "green")
            # Actual PiShock connection state is updated periodically from services.
            self.pishock_status.set_status("Checking...", "orange")
            self.whisper_status.set_status("Running", "green")

            active_features: list[str] = []
            if self.feature_ear_tail.variable.get():
                active_features.append("Ear/Tail pull")
            if self.feature_pronouns.variable.get():
                active_features.append("Pronouns")

            if active_features:
                self.active_features_status.set_status(", ".join(active_features), "green")
            else:
                self.active_features_status.set_status("None", "grey")
        else:
            self.osc_status.set_status("Idle", "grey")
            self.pishock_status.set_status("Disconnected", "grey")
            self.whisper_status.set_status("Stopped", "grey")
            self.active_features_status.set_status("OFF", "grey")

    def update_osc_status(self, osc_status: dict) -> None:
        """Update the VRChat OSC status line with live diagnostics."""
        if not self._is_running:
            return

        messages = osc_status.get("messages_last_10s", 0)
        # Prefer pet ear/tail pull diagnostics, falling back to trainer
        # parameter counts if older diagnostics are present.
        expected = osc_status.get("expected_pet_pull_params_total")
        found = osc_status.get("found_pet_pull_params")

        if expected is None or found is None:
            expected = osc_status.get("expected_trainer_params_total", 0)
            found = osc_status.get("found_trainer_params", 0)

        missing = max(expected - found, 0)

        if expected:
            text = f"Messages received: {messages} (10s), Parameters found: {found}/{expected} ({missing} missing)"
        else:
            text = f"Messages received: {messages} (10s), Parameters found: 0/0"

        if messages == 0:
            colour = "red"
        elif missing > 0:
            colour = "orange"
        else:
            colour = "green"

        self.osc_status.set_status(text, colour)

    # Internal callbacks -------------------------------------------------
    def _on_any_setting_changed(self, *_) -> None:
        if self._suppress_callbacks:
            return
        if self.on_settings_change is not None:
            self.on_settings_change(self.collect_settings())

    def _toggle_start(self) -> None:
        new_state = not self._is_running
        self.set_running_state(new_state)
        if self.on_start is not None:
            self.on_start(new_state)
