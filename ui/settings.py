import tkinter as tk
from tkinter import ttk

from .shared import LabeledCombobox


class SettingsTab(ttk.Frame):
    """Settings tab UI.

    Currently only exposes input device configuration.
    Backend code can use `set_input_devices` and `input_device` to
    integrate with actual audio device discovery.
    """

    def __init__(self, master, on_settings_change=None, *, input_device_var: tk.StringVar | None = None, **kwargs) -> None:
        super().__init__(master, **kwargs)

        self.on_settings_change = on_settings_change

        self.input_device_row = LabeledCombobox(self, "Input device", variable=input_device_var)
        self.input_device_row.grid(row=0, column=0, sticky="ew", padx=12, pady=12)

        self.input_device_row.variable.trace_add("write", self._on_any_setting_changed)

        self.columnconfigure(0, weight=1)

    @property
    def input_device(self) -> str:
        return self.input_device_row.variable.get()

    def set_input_devices(self, devices) -> None:
        """Populate available audio input devices."""
        self.input_device_row.set_values(devices)
        if devices and not self.input_device_row.variable.get():
            self.input_device_row.variable.set(devices[0])

    def collect_settings(self) -> dict:
        return {
            "input_device": self.input_device,
        }

    def _on_any_setting_changed(self, *_) -> None:
        if self.on_settings_change is not None:
            self.on_settings_change(self.collect_settings())
