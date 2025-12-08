import tkinter as tk
from tkinter import ttk

from .shared import (
    LabeledCombobox,
    LabeledEntry,
    ScrollableFrame,
)


def _create_pishock_credentials_frame(
    master,
    *,
    frame_text: str = "PiShock credentials",
) -> tuple[ttk.LabelFrame, LabeledEntry, LabeledEntry]:
    """Create a PiShock credential section shared by Trainer/Pet tabs."""
    frame = ttk.LabelFrame(master, text=frame_text)
    frame.columnconfigure(0, weight=1)

    username = LabeledEntry(frame, "Username")
    username.grid(row=0, column=0, sticky="ew", pady=(0, 4))

    api_key = LabeledEntry(frame, "API key", show="*")
    api_key.grid(row=1, column=0, sticky="ew")

    return frame, username, api_key

class PetTab(ScrollableFrame):
    """Pet tab UI."""

    def __init__(self, master, on_settings_change=None, *, input_device_var: tk.StringVar | None = None, **kwargs) -> None:
        super().__init__(master, **kwargs)

        self.on_settings_change = on_settings_change
        self._suppress_callbacks = False

        self._build_input_device_row(input_device_var)
        self._build_pishock_section()

        self.container.columnconfigure(0, weight=1)

    def _build_input_device_row(self, variable: tk.StringVar | None) -> None:
        self.input_device_row = LabeledCombobox(self.container, "Input device", variable=variable)
        self.input_device_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

    def _build_pishock_section(self) -> None:
        frame, self.pishock_username, self.pishock_api_key = _create_pishock_credentials_frame(self.container)
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

    # Internal callbacks -------------------------------------------------
    def _on_any_setting_changed(self, *_) -> None:
        if self._suppress_callbacks:
            return
        if self.on_settings_change is not None:
            self.on_settings_change(self.collect_settings())
