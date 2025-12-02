import tkinter as tk
from tkinter import ttk, simpledialog, messagebox

from .shared import (
    LabeledEntry,
    LabeledCheckbutton,
    LabeledCombobox,
    StatusIndicator,
    ScrollableFrame,
    create_features_frame,
    create_pishock_credentials_frame,
    create_running_status_frame,
)


class TrainerTab(ScrollableFrame):
    """Trainer tab UI."""

    def __init__(
        self,
        master,
        on_settings_change=None,
        on_start=None,
        on_profile_selected=None,
        on_profile_renamed=None,
        on_profile_deleted=None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)

        self.on_settings_change = on_settings_change
        self.on_start = on_start
        self.on_profile_selected = on_profile_selected
        self.on_profile_renamed = on_profile_renamed
        self.on_profile_deleted = on_profile_deleted
        self._suppress_callbacks = False
        self._is_running = False
        self._detail_frames: list[ttk.Frame] = []

        self._build_profile_section()
        self._build_pishock_section()
        self._build_features_section()
        self._build_word_lists_section()
        self._build_difficulty_section()
        self._build_controls_section()

        for col in range(2):
            self.container.columnconfigure(col, weight=1)

        self._update_profile_visibility()

    # Profile management -------------------------------------------------
    def _build_profile_section(self) -> None:
        frame = ttk.LabelFrame(self.container, text="Profile")
        frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6))
        frame.columnconfigure(0, weight=1)

        self.profile_row = LabeledCombobox(frame, "Profile")
        self.profile_row.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 4))
        self.profile_row.combobox.bind("<<ComboboxSelected>>", self._on_profile_selected)

        new_button = ttk.Button(frame, text="New", width=10, command=self._new_profile)
        rename_button = ttk.Button(frame, text="Rename", width=10, command=self._rename_profile)
        delete_button = ttk.Button(frame, text="Delete", width=10, command=self._delete_profile)

        new_button.grid(row=1, column=0, sticky="w", pady=(0, 4))
        rename_button.grid(row=1, column=1, sticky="w", pady=(0, 4), padx=(8, 0))
        delete_button.grid(row=1, column=2, sticky="w", pady=(0, 4), padx=(8, 0))

        info_label = ttk.Label(frame, text="All settings are saved on change.")
        info_label.grid(row=2, column=0, columnspan=4, sticky="w")

    def _new_profile(self) -> None:
        name = simpledialog.askstring("New profile", "Enter new profile name:", parent=self.winfo_toplevel())
        if not name:
            return

        values = list(self.profile_row.combobox["values"])
        if name in values:
            messagebox.showerror("Profile exists", "A profile with that name already exists.")
            return

        values.append(name)
        self.profile_row.set_values(values)
        self.profile_row.variable.set(name)
        self._on_profile_selected()

    def _rename_profile(self) -> None:
        current = self.profile_row.variable.get()
        if not current:
            messagebox.showinfo("No profile selected", "Select a profile to rename.")
            return

        new_name = simpledialog.askstring("Rename profile", "Enter new profile name:", initialvalue=current, parent=self.winfo_toplevel())
        if not new_name or new_name == current:
            return

        values = list(self.profile_row.combobox["values"])
        if new_name in values:
            messagebox.showerror("Profile exists", "A profile with that name already exists.")
            return

        try:
            index = values.index(current)
        except ValueError:
            index = None

        if index is not None:
            values[index] = new_name
        else:
            values.append(new_name)

        self.profile_row.set_values(values)
        self.profile_row.variable.set(new_name)
        if self.on_profile_renamed is not None:
            self.on_profile_renamed(current, new_name)
        self._on_profile_selected()

    def _delete_profile(self) -> None:
        current = self.profile_row.variable.get()
        if not current:
            messagebox.showinfo("No profile selected", "Select a profile to delete.")
            return

        confirm = messagebox.askyesno(
            "Delete profile",
            f"Are you sure you want to delete profile '{current}'?",
            parent=self.winfo_toplevel(),
        )
        if not confirm:
            return

        values = list(self.profile_row.combobox["values"])
        if current not in values:
            return

        values.remove(current)
        self.profile_row.set_values(values)

        # Choose a new selection if any profiles remain.
        new_selection = values[0] if values else ""
        self.profile_row.variable.set(new_selection)

        if self.on_profile_deleted is not None:
            self.on_profile_deleted(current)

        self._on_profile_selected()

    def set_profiles(self, profiles) -> None:
        """Populate the list of known profiles."""
        self._suppress_callbacks = True
        try:
            self.profile_row.set_values(profiles)
            if profiles and not self.profile_row.variable.get():
                self.profile_row.variable.set(profiles[0])
        finally:
            self._suppress_callbacks = False
        self._update_profile_visibility()

    # PiShock credentials ------------------------------------------------
    def _build_pishock_section(self) -> None:
        frame, self.pishock_username, self.pishock_api_key = create_pishock_credentials_frame(self.container)
        frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12, pady=6)
        self._detail_frames.append(frame)

        self.pishock_username.variable.trace_add("write", self._on_any_setting_changed)
        self.pishock_api_key.variable.trace_add("write", self._on_any_setting_changed)

    # Feature toggles ----------------------------------------------------
    def _build_features_section(self) -> None:
        frame, features = create_features_frame(
            self.container,
            ["Focus", "Proximity", "Tricks", "Scolding"],
        )
        frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=12, pady=6)
        self._detail_frames.append(frame)

        self.feature_focus, self.feature_proximity, self.feature_tricks, self.feature_scolding = features

        for feature in features:
            feature.variable.trace_add("write", self._on_any_setting_changed)

    # Word lists ---------------------------------------------------------
    def _build_word_lists_section(self) -> None:
        frame = ttk.LabelFrame(self.container, text="Word lists")
        frame.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=12, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        self._detail_frames.append(frame)

        # Names ----------------------------------------------------------
        names_label = ttk.Label(frame, text="Names (one per line)")
        names_label.grid(row=0, column=0, sticky="w")

        names_text_frame = ttk.Frame(frame)
        names_text_frame.grid(row=1, column=0, sticky="nsew", pady=(2, 6))
        names_text_frame.columnconfigure(0, weight=1)

        self.names_text = tk.Text(names_text_frame, height=6, wrap="word")
        names_scroll = ttk.Scrollbar(names_text_frame, orient="vertical", command=self.names_text.yview)
        self.names_text.configure(yscrollcommand=names_scroll.set)

        self.names_text.grid(row=0, column=0, sticky="nsew")
        names_scroll.grid(row=0, column=1, sticky="ns")
        self.names_text.bind("<FocusOut>", self._on_any_setting_changed)

        # Scolding words -------------------------------------------------
        scolding_label = ttk.Label(frame, text="Scolding words (one per line)")
        scolding_label.grid(row=0, column=1, sticky="w")

        scolding_text_frame = ttk.Frame(frame)
        scolding_text_frame.grid(row=1, column=1, sticky="nsew", pady=(2, 6))
        scolding_text_frame.columnconfigure(0, weight=1)

        self.scolding_words_text = tk.Text(scolding_text_frame, height=6, wrap="word")
        scolding_scroll = ttk.Scrollbar(scolding_text_frame, orient="vertical", command=self.scolding_words_text.yview)
        self.scolding_words_text.configure(yscrollcommand=scolding_scroll.set)

        self.scolding_words_text.grid(row=0, column=0, sticky="nsew")
        scolding_scroll.grid(row=0, column=1, sticky="ns")
        self.scolding_words_text.bind("<FocusOut>", self._on_any_setting_changed)

    # Difficulty ---------------------------------------------------------
    def _build_difficulty_section(self) -> None:
        frame = ttk.LabelFrame(self.container, text="Difficulty")
        frame.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=12, pady=6)
        frame.columnconfigure(0, weight=1)
        self._detail_frames.append(frame)

        self.difficulty_row = LabeledCombobox(frame, "Level", values=["Easy", "Normal", "Hard"])
        self.difficulty_row.variable.set("Normal")
        self.difficulty_row.grid(row=0, column=0, sticky="ew")
        self.difficulty_row.variable.trace_add("write", self._on_any_setting_changed)

    # Controls + status --------------------------------------------------
    def _build_controls_section(self) -> None:
        control_frame = ttk.Frame(self.container)
        control_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", padx=12, pady=6)
        control_frame.columnconfigure(0, weight=1)
        self._detail_frames.append(control_frame)

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
        """Collect the current trainer settings into a dictionary."""
        return {
            "profile": self.profile_row.variable.get(),
            "pishock_username": self.pishock_username.variable.get(),
            "pishock_api_key": self.pishock_api_key.variable.get(),
            "feature_focus": self.feature_focus.variable.get(),
            "feature_proximity": self.feature_proximity.variable.get(),
            "feature_tricks": self.feature_tricks.variable.get(),
            "feature_scolding": self.feature_scolding.variable.get(),
            "difficulty": self.difficulty_row.variable.get(),
            "names": self._get_words_from_text(self.names_text),
            "command_words": [],
            "scolding_words": self._get_words_from_text(self.scolding_words_text),
        }

    def apply_profile_settings(self, settings: dict | None) -> None:
        """Apply settings for the currently selected profile without triggering callbacks."""
        self._suppress_callbacks = True
        try:
            if not settings:
                # Reset to defaults if nothing is stored yet.
                self.pishock_username.variable.set("")
                self.pishock_api_key.variable.set("")
                self.feature_focus.variable.set(False)
                self.feature_proximity.variable.set(False)
                self.feature_tricks.variable.set(False)
                self.feature_scolding.variable.set(False)
                self.difficulty_row.variable.set("Normal")
                self._set_words_text(self.names_text, [])
                self._set_words_text(self.scolding_words_text, [])
            else:
                # Profile name may come from config; keep UI combobox in sync.
                profile_name = settings.get("profile")
                if profile_name:
                    self.profile_row.variable.set(profile_name)

                self.pishock_username.variable.set(settings.get("pishock_username", ""))
                self.pishock_api_key.variable.set(settings.get("pishock_api_key", ""))
                self.feature_focus.variable.set(bool(settings.get("feature_focus")))
                self.feature_proximity.variable.set(bool(settings.get("feature_proximity")))
                self.feature_tricks.variable.set(bool(settings.get("feature_tricks")))
                self.feature_scolding.variable.set(bool(settings.get("feature_scolding")))
                self.difficulty_row.variable.set(settings.get("difficulty") or "Normal")
                self._set_words_text(self.names_text, settings.get("names", []))
                self._set_words_text(self.scolding_words_text, settings.get("scolding_words", []))
        finally:
            self._suppress_callbacks = False

        self._update_profile_visibility()

    def set_running_state(self, running: bool) -> None:
        """Update UI to reflect running state."""
        self._is_running = running
        self.start_button.configure(text="Stop" if running else "Start")

        if running:
            self.osc_status.set_status("Receiving parameters", "green")
            # Actual PiShock connection state is updated periodically from services.
            self.pishock_status.set_status("Checking...", "orange")
            self.whisper_status.set_status("Running", "green")

            active_features: list[str] = []
            if self.feature_focus.variable.get():
                active_features.append("Focus")
            if self.feature_proximity.variable.get():
                active_features.append("Proximity")
            if self.feature_tricks.variable.get():
                active_features.append("Tricks")
            if self.feature_scolding.variable.get():
                active_features.append("Scolding")

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

    def append_whisper_log(self, text: str) -> None:
        """Append a line to the Whisper text log."""
        self.whisper_log.configure(state="normal")
        self.whisper_log.insert("end", text + "\n")
        self.whisper_log.see("end")
        self.whisper_log.configure(state="disabled")

    # Internal helpers ---------------------------------------------------
    def _get_words_from_text(self, widget: tk.Text) -> list[str]:
        """Return a cleaned list of words from a Text widget."""
        raw = widget.get("1.0", "end").strip()
        if not raw:
            return []
        # Treat each non-empty line as a separate word/phrase.
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _set_words_text(self, widget: tk.Text, words) -> None:
        """Populate a Text widget from a stored list or string."""
        widget.delete("1.0", "end")
        if not words:
            return
        if isinstance(words, str):
            widget.insert("1.0", words)
        else:
            widget.insert("1.0", "\n".join(str(w) for w in words))

    # Internal callbacks -------------------------------------------------
    def _on_any_setting_changed(self, *_) -> None:
        if self._suppress_callbacks:
            return
        if self.on_settings_change is not None:
            self.on_settings_change(self.collect_settings())

    def _on_profile_selected(self, *_) -> None:
        if self._suppress_callbacks:
            return
        self._update_profile_visibility()
        if self.on_profile_selected is not None:
            self.on_profile_selected(self.profile_row.variable.get())

    def _update_profile_visibility(self) -> None:
        """Show or hide trainer controls based on whether a valid profile is selected."""
        selected = self.profile_row.variable.get()
        valid_profiles = set(self.profile_row.combobox["values"])
        has_valid_profile = bool(selected and selected in valid_profiles)

        for frame in self._detail_frames:
            if has_valid_profile:
                frame.grid()
            else:
                frame.grid_remove()

    def _toggle_start(self) -> None:
        new_state = not self._is_running
        self.set_running_state(new_state)
        if self.on_start is not None:
            self.on_start(new_state)
