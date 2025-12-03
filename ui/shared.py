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


def create_running_status_frame(
    master,
    *,
    frame_text: str = "Running status",
) -> tuple[ttk.LabelFrame, StatusIndicator, StatusIndicator, StatusIndicator, tk.Text, StatusIndicator]:
    """Create the shared running status section (OSC, PiShock, Whisper, log, active features)."""
    status_frame = ttk.LabelFrame(master, text=frame_text)
    status_frame.columnconfigure(0, weight=1)

    # VRChat OSC
    osc_status = StatusIndicator(status_frame, "VRChat OSC")
    osc_status.grid(row=0, column=0, sticky="w", padx=6, pady=(4, 0))

    # PiShock
    pishock_status = StatusIndicator(status_frame, "PiShock")
    pishock_status.grid(row=1, column=0, sticky="w", padx=6, pady=(2, 0))

    # Whisper
    whisper_frame = ttk.Frame(status_frame)
    whisper_frame.grid(row=2, column=0, sticky="nsew", padx=6, pady=(4, 0))
    whisper_frame.columnconfigure(0, weight=1)

    whisper_status = StatusIndicator(whisper_frame, "Whisper")
    whisper_status.grid(row=0, column=0, sticky="w")

    log_label = ttk.Label(whisper_frame, text="Text log:")
    log_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

    whisper_log = tk.Text(whisper_frame, height=6, wrap="word", state="disabled")
    whisper_log.grid(row=2, column=0, sticky="nsew", pady=(2, 4))

    # Active features
    active_features_status = StatusIndicator(status_frame, "Active features")
    active_features_status.grid(row=3, column=0, sticky="w", padx=6, pady=(2, 6))

    return status_frame, osc_status, pishock_status, whisper_status, whisper_log, active_features_status


def update_running_state_ui(
    *,
    running: bool,
    start_button: ttk.Button,
    osc_status: StatusIndicator,
    pishock_status: StatusIndicator,
    whisper_status: StatusIndicator,
    active_features_status: StatusIndicator,
    active_features: list[str],
) -> None:
    """Synchronise common running-state UI pieces between Trainer and Pet tabs."""
    start_button.configure(text="Stop" if running else "Start")

    if running:
        osc_status.set_status("Receiving parameters", "green")
        # Actual PiShock connection state is updated periodically from services.
        pishock_status.set_status("Checking...", "orange")
        whisper_status.set_status("Running", "green")

        if active_features:
            active_features_status.set_status(", ".join(active_features), "green")
        else:
            active_features_status.set_status("None", "grey")
    else:
        osc_status.set_status("Idle", "grey")
        pishock_status.set_status("Disconnected", "grey")
        whisper_status.set_status("Stopped", "grey")
        active_features_status.set_status("OFF", "grey")


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
