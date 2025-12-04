import tkinter as tk
from tkinter import ttk

from .shared import (
    LabeledCombobox,
    ScrollableFrame,
    create_pishock_credentials_frame,
)

class PetTab(ScrollableFrame):
    """Pet tab UI."""

    def __init__(self, master, on_settings_change=None, *, input_device_var: tk.StringVar | None = None, **kwargs) -> None:
        super().__init__(master, **kwargs)

        self.on_settings_change = on_settings_change
        self._suppress_callbacks = False
        self._feature_focus_enabled = False
        self._feature_proximity_enabled = False
        self._feature_tricks_enabled = False
        self._feature_scolding_enabled = False
        self._feature_ear_tail_enabled = False
        self._feature_pronouns_enabled = False

        self._build_input_device_row(input_device_var)
        self._build_pishock_section()

        self.container.columnconfigure(0, weight=1)

    def _build_input_device_row(self, variable: tk.StringVar | None) -> None:
        self.input_device_row = LabeledCombobox(self.container, "Input device", variable=variable)
        self.input_device_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

    def _build_pishock_section(self) -> None:
        frame, self.pishock_username, self.pishock_api_key = create_pishock_credentials_frame(self.container)
        frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(6, 12))

        self.pishock_username.variable.trace_add("write", self._on_any_setting_changed)
        self.pishock_api_key.variable.trace_add("write", self._on_any_setting_changed)

    # Public helpers -----------------------------------------------------
    @property
    def input_device(self) -> str:
        return self.input_device_row.variable.get()

    def set_input_devices(self, devices) -> None:
        self.input_device_row.set_values(devices)
        if devices and not self.input_device_row.variable.get():
            self.input_device_row.variable.set(devices[0])

    def collect_settings(self) -> dict:
        """Collect the current pet settings into a dictionary."""
        return {
            "pishock_username": self.pishock_username.variable.get(),
            "pishock_api_key": self.pishock_api_key.variable.get(),
        }

    def apply_settings(self, settings: dict | None) -> None:
        """Apply stored pet settings without triggering callbacks."""
        self._suppress_callbacks = True
        try:
            if not settings:
                self.pishock_username.variable.set("")
                self.pishock_api_key.variable.set("")
            else:
                self.pishock_username.variable.set(settings.get("pishock_username", ""))
                self.pishock_api_key.variable.set(settings.get("pishock_api_key", ""))
        finally:
            self._suppress_callbacks = False

    def set_feature_flags(
        self,
        *,
        feature_focus: bool = False,
        feature_proximity: bool = False,
        feature_tricks: bool = False,
        feature_scolding: bool = False,
        feature_ear_tail: bool = False,
        feature_pronouns: bool = False,
    ) -> None:
        """Receive feature toggles controlled from the trainer side."""
        self._feature_focus_enabled = bool(feature_focus)
        self._feature_proximity_enabled = bool(feature_proximity)
        self._feature_tricks_enabled = bool(feature_tricks)
        self._feature_scolding_enabled = bool(feature_scolding)
        self._feature_ear_tail_enabled = bool(feature_ear_tail)
        self._feature_pronouns_enabled = bool(feature_pronouns)

    # Internal callbacks -------------------------------------------------
    def _on_any_setting_changed(self, *_) -> None:
        if self._suppress_callbacks:
            return
        if self.on_settings_change is not None:
            self.on_settings_change(self.collect_settings())
