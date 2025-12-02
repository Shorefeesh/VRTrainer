import tkinter as tk
from tkinter import ttk


class LabeledEntry(ttk.Frame):
    """A label with an entry field."""

    def __init__(self, master, text: str, **entry_kwargs) -> None:
        super().__init__(master)
        self.variable = tk.StringVar()

        self.label = ttk.Label(self, text=text)
        self.entry = ttk.Entry(self, textvariable=self.variable, **entry_kwargs)

        self.label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.entry.grid(row=0, column=1, sticky="ew")
        self.columnconfigure(1, weight=1)


class LabeledCombobox(ttk.Frame):
    """A label with a combobox."""

    def __init__(self, master, text: str, values=None, **combo_kwargs) -> None:
        super().__init__(master)
        if values is None:
            values = []

        self.variable = tk.StringVar()

        self.label = ttk.Label(self, text=text)
        self.combobox = ttk.Combobox(
            self,
            textvariable=self.variable,
            values=values,
            state=combo_kwargs.pop("state", "readonly"),
            **combo_kwargs,
        )

        self.label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.combobox.grid(row=0, column=1, sticky="ew")
        self.columnconfigure(1, weight=1)

    def set_values(self, values) -> None:
        self.combobox["values"] = values


class LabeledCheckbutton(ttk.Frame):
    """A single checkbutton with its own BooleanVar."""

    def __init__(self, master, text: str, **check_kwargs) -> None:
        super().__init__(master)
        self.variable = tk.BooleanVar()

        self.checkbutton = ttk.Checkbutton(
            self,
            text=text,
            variable=self.variable,
            **check_kwargs,
        )
        self.checkbutton.grid(row=0, column=0, sticky="w")


class StatusIndicator(ttk.Frame):
    """Label + status text, colour-coded."""

    def __init__(self, master, text: str, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._status_var = tk.StringVar(value="Unknown")

        self._label = ttk.Label(self, text=f"{text}:")
        self._value_label = ttk.Label(self, textvariable=self._status_var, foreground="grey")

        self._label.grid(row=0, column=0, sticky="w")
        self._value_label.grid(row=0, column=1, sticky="w", padx=(4, 0))

    def set_status(self, text: str, colour: str = "grey") -> None:
        self._status_var.set(text)
        self._value_label.configure(foreground=colour)
