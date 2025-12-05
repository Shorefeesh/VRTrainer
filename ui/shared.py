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

    def __init__(self, master, text: str, values=None, *, variable: tk.StringVar | None = None, **combo_kwargs) -> None:
        super().__init__(master)
        if values is None:
            values = []

        self.variable = variable or tk.StringVar()

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


class LabeledScale(ttk.Frame):
    """A label with a horizontal scale and live value indicator."""

    def __init__(
        self,
        master,
        text: str,
        *,
        from_: float = 0.0,
        to: float = 2.0,
        resolution: float = 0.05,
        initial: float = 1.0,
    ) -> None:
        super().__init__(master)

        self.variable = tk.DoubleVar(value=initial)

        label = ttk.Label(self, text=text)
        label.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.scale = ttk.Scale(
            self,
            variable=self.variable,
            from_=from_,
            to=to,
            orient="horizontal",
        )
        self.scale.grid(row=0, column=1, sticky="ew")

        self.value_label = ttk.Label(self, width=6, anchor="e")
        self.value_label.grid(row=0, column=2, sticky="e", padx=(8, 0))

        self.columnconfigure(1, weight=1)

        # Keep the displayed multiplier in sync.
        self.variable.trace_add("write", lambda *_: self._update_value_label())
        self._update_value_label()

        # Enforce step size manually because ttk.Scale does not support resolution.
        def _snap_to_resolution(value: float) -> float:
            step = resolution
            if step <= 0:
                return value
            snapped = round(value / step) * step
            return max(from_, min(to, snapped))

        def _on_move(*_) -> None:
            snapped = _snap_to_resolution(self.variable.get())
            if snapped != self.variable.get():
                self.variable.set(snapped)

        self.scale.configure(command=lambda _val: _on_move())

    def _update_value_label(self) -> None:
        self.value_label.configure(text=f"{self.variable.get():.2f}x")


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


class ScrollableFrame(ttk.Frame):
    """A frame with a vertical scrollbar that appears when content is taller than the available space."""

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, **kwargs)

        self._canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self._v_scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self.container = ttk.Frame(self._canvas)

        # Keep scroll region and width in sync with content.
        self._canvas_window = self._canvas.create_window((0, 0), window=self.container, anchor="nw")
        self.container.bind(
            "<Configure>",
            lambda event: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>",
            lambda event: self._canvas.itemconfigure(self._canvas_window, width=event.width),
        )

        self._canvas.configure(yscrollcommand=self._v_scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        self._v_scrollbar.pack(side="right", fill="y")


def create_pishock_credentials_frame(
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


def create_features_frame(
    master,
    labels: list[str],
    *,
    frame_text: str = "Features",
) -> tuple[ttk.LabelFrame, list[LabeledCheckbutton]]:
    """Create a simple features frame with one checkbox per label."""
    frame = ttk.LabelFrame(master, text=frame_text)

    features: list[LabeledCheckbutton] = []
    for row, label in enumerate(labels):
        feature = LabeledCheckbutton(frame, label)
        feature.grid(row=row, column=0, sticky="w")
        features.append(feature)

    return frame, features



def update_osc_status_indicator(
    *,
    is_running: bool,
    status_indicator: StatusIndicator,
    osc_status: dict,
    primary_expected_key: str,
    primary_found_key: str,
    fallback_expected_key: str | None = None,
    fallback_found_key: str | None = None,
) -> None:
    """Update the VRChat OSC status line with live diagnostics."""
    if not is_running:
        return

    if osc_status.get("enabled") is False:
        status_indicator.set_status("Disabled (handled on pet side)", "grey")
        return

    messages = osc_status.get("messages_last_10s", 0)

    expected = osc_status.get(primary_expected_key)
    found = osc_status.get(primary_found_key)

    if (expected is None or found is None) and fallback_expected_key and fallback_found_key:
        expected = osc_status.get(fallback_expected_key, 0)
        found = osc_status.get(fallback_found_key, 0)

    expected = expected or 0
    found = found or 0
    missing = max(expected - found, 0)

    if expected:
        text = (
            f"Messages received: {messages} (10s), "
            f"Parameters found: {found}/{expected} ({missing} missing)"
        )
    else:
        text = f"Messages received: {messages} (10s), Parameters found: 0/0"

    if messages == 0:
        colour = "red"
    elif missing > 0:
        colour = "orange"
    else:
        colour = "green"

    status_indicator.set_status(text, colour)
