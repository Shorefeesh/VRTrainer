import tkinter as tk
from tkinter import ttk, simpledialog, messagebox

from .shared import LabeledCheckbutton, LabeledCombobox, LabeledScale, ScrollableFrame


class TrainerTab(ScrollableFrame):
    """Trainer tab UI."""

    def __init__(
        self,
        master,
        on_settings_change=None,
        on_profile_selected=None,
        on_profile_renamed=None,
        on_profile_deleted=None,
        input_device_var: tk.StringVar | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)

        self.on_settings_change = on_settings_change
        self.on_profile_selected = on_profile_selected
        self.on_profile_renamed = on_profile_renamed
        self.on_profile_deleted = on_profile_deleted
        self._suppress_callbacks = False
        self._detail_frames: list[ttk.Frame] = []
        self._word_game_options: list[str] = ["None", "Pronouns"]

        self._build_input_device_row(input_device_var)
        self._build_profile_section()
        self._build_features_section()
        self._build_word_lists_section()
        self._build_scaling_section()

        for col in range(2):
            self.container.columnconfigure(col, weight=1)

        self._update_profile_visibility()

    # Input device -------------------------------------------------------
    def _build_input_device_row(self, variable: tk.StringVar | None) -> None:
        self.input_device_row = LabeledCombobox(self.container, "Input device", variable=variable)
        self.input_device_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6))

    # Profile management -------------------------------------------------
    def _build_profile_section(self) -> None:
        frame = ttk.LabelFrame(self.container, text="Profile")
        frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
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

    # Feature toggles ----------------------------------------------------
    def _build_features_section(self) -> None:
        frame = ttk.LabelFrame(self.container, text="Features")
        frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=12, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        self._detail_frames.append(frame)

        self.feature_focus = LabeledCheckbutton(frame, "Focus")
        self.feature_focus.grid(row=0, column=0, sticky="w")

        self.feature_proximity = LabeledCheckbutton(frame, "Proximity")
        self.feature_proximity.grid(row=1, column=0, sticky="w")

        self.feature_tricks = LabeledCheckbutton(frame, "Tricks")
        self.feature_tricks.grid(row=2, column=0, sticky="w")

        self.feature_scolding = LabeledCheckbutton(frame, "Scolding words")
        self.feature_scolding.grid(row=3, column=0, sticky="w")

        self.feature_forbidden_words = LabeledCheckbutton(frame, "Forbidden words")
        self.feature_forbidden_words.grid(row=4, column=0, sticky="w")

        # Keep word game selection aligned with the combobox.
        ttk.Label(frame, text="Word game").grid(row=5, column=0, sticky="w", pady=(4, 0))
        self.word_game_var = tk.StringVar(value=self._word_game_options[0])
        self.word_game_combo = ttk.Combobox(
            frame,
            textvariable=self.word_game_var,
            state="readonly",
            values=self._word_game_options,
        )
        self.word_game_combo.grid(row=5, column=1, sticky="ew", pady=(4, 0))

        self.feature_ear_tail = LabeledCheckbutton(frame, "Ear/Tail pull")
        self.feature_ear_tail.grid(row=0, column=1, sticky="w")

        for feature in (
            self.feature_focus,
            self.feature_proximity,
            self.feature_tricks,
            self.feature_scolding,
            self.feature_forbidden_words,
            self.feature_ear_tail,
        ):
            feature.variable.trace_add("write", self._on_any_setting_changed)

        self.word_game_var.trace_add("write", self._on_any_setting_changed)

    # Word lists ---------------------------------------------------------
    def _build_word_lists_section(self) -> None:
        frame = ttk.LabelFrame(self.container, text="Word lists")
        frame.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=12, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)
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

        # Forbidden words ------------------------------------------------
        forbidden_label = ttk.Label(frame, text="Forbidden (one per line)")
        forbidden_label.grid(row=0, column=2, sticky="w")

        forbidden_text_frame = ttk.Frame(frame)
        forbidden_text_frame.grid(row=1, column=2, sticky="nsew", pady=(2, 6))
        forbidden_text_frame.columnconfigure(0, weight=1)

        self.forbidden_words_text = tk.Text(forbidden_text_frame, height=6, wrap="word")
        forbidden_scroll = ttk.Scrollbar(forbidden_text_frame, orient="vertical", command=self.forbidden_words_text.yview)
        self.forbidden_words_text.configure(yscrollcommand=forbidden_scroll.set)

        self.forbidden_words_text.grid(row=0, column=0, sticky="nsew")
        forbidden_scroll.grid(row=0, column=1, sticky="ns")
        self.forbidden_words_text.bind("<FocusOut>", self._on_any_setting_changed)

    # Scaling ------------------------------------------------------------
    def _build_scaling_section(self) -> None:
        frame = ttk.LabelFrame(self.container, text="Scaling")
        frame.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=12, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        self._detail_frames.append(frame)

        self.delay_scale = LabeledScale(frame, "Delay scale", from_=0.0, to=2.0, resolution=0.05, initial=1.0)
        self.delay_scale.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 4))

        self.cooldown_scale = LabeledScale(frame, "Cooldown scale", from_=0.0, to=2.0, resolution=0.05, initial=1.0)
        self.cooldown_scale.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 4))

        self.duration_scale = LabeledScale(frame, "Duration scale", from_=0.0, to=2.0, resolution=0.05, initial=1.0)
        self.duration_scale.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        self.strength_scale = LabeledScale(frame, "Strength scale", from_=0.0, to=2.0, resolution=0.05, initial=1.0)
        self.strength_scale.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        for scale in (self.delay_scale, self.cooldown_scale, self.duration_scale, self.strength_scale):
            scale.variable.trace_add("write", self._on_any_setting_changed)

    # Public helpers -----------------------------------------------------
    @property
    def input_device(self) -> str:
        return self.input_device_row.variable.get()

    def set_input_devices(self, devices) -> None:
        self.input_device_row.set_values(devices)
        if devices and not self.input_device_row.variable.get():
            self.input_device_row.variable.set(devices[0])

    def collect_settings(self) -> dict:
        """Collect the current trainer settings into a dictionary."""
        return {
            "profile": self.profile_row.variable.get(),
            "feature_focus": self.feature_focus.variable.get(),
            "feature_proximity": self.feature_proximity.variable.get(),
            "feature_tricks": self.feature_tricks.variable.get(),
            "feature_scolding": self.feature_scolding.variable.get(),
            "feature_forbidden_words": self.feature_forbidden_words.variable.get(),
            "feature_ear_tail": self.feature_ear_tail.variable.get(),
            "word_game": self.word_game_var.get() or self._word_game_options[0],
            # Keep compatibility with the existing pronouns feature by deriving it from the word game choice.
            "feature_pronouns": (self.word_game_var.get() or "").lower() == "pronouns",
            "delay_scale": float(self.delay_scale.variable.get()),
            "cooldown_scale": float(self.cooldown_scale.variable.get()),
            "duration_scale": float(self.duration_scale.variable.get()),
            "strength_scale": float(self.strength_scale.variable.get()),
            "names": self._get_words_from_text(self.names_text),
            "scolding_words": self._get_words_from_text(self.scolding_words_text),
            "forbidden_words": self._get_words_from_text(self.forbidden_words_text),
        }

    def apply_profile_settings(self, settings: dict | None) -> None:
        """Apply settings for the currently selected profile without triggering callbacks."""
        self._suppress_callbacks = True
        try:
            if not settings:
                # Reset to defaults if nothing is stored yet.
                self.feature_focus.variable.set(False)
                self.feature_proximity.variable.set(False)
                self.feature_tricks.variable.set(False)
                self.feature_scolding.variable.set(False)
                self.feature_forbidden_words.variable.set(False)
                self.feature_ear_tail.variable.set(False)
                self.word_game_var.set(self._word_game_options[0])
                self.delay_scale.variable.set(1.0)
                self.cooldown_scale.variable.set(1.0)
                self.duration_scale.variable.set(1.0)
                self.strength_scale.variable.set(1.0)
                self._set_words_text(self.names_text, [])
                self._set_words_text(self.scolding_words_text, [])
                self._set_words_text(self.forbidden_words_text, [])
            else:
                # Profile name may come from config; keep UI combobox in sync.
                profile_name = settings.get("profile")
                if profile_name:
                    self.profile_row.variable.set(profile_name)

                self.feature_focus.variable.set(bool(settings.get("feature_focus")))
                self.feature_proximity.variable.set(bool(settings.get("feature_proximity")))
                self.feature_tricks.variable.set(bool(settings.get("feature_tricks")))
                self.feature_scolding.variable.set(bool(settings.get("feature_scolding")))
                self.feature_forbidden_words.variable.set(bool(settings.get("feature_forbidden_words")))
                self.feature_ear_tail.variable.set(bool(settings.get("feature_ear_tail")))

                word_game = settings.get("word_game") or (
                    self._word_game_options[1] if settings.get("feature_pronouns") else self._word_game_options[0]
                )
                if word_game not in self._word_game_options:
                    self._word_game_options.append(word_game)
                    self.word_game_combo["values"] = self._word_game_options
                self.word_game_var.set(word_game)

                delay_scale = settings.get("delay_scale")
                cooldown_scale = settings.get("cooldown_scale")
                duration_scale = settings.get("duration_scale")
                strength_scale = settings.get("strength_scale")

                self.delay_scale.variable.set(float(delay_scale if delay_scale is not None else 1.0))
                self.cooldown_scale.variable.set(float(cooldown_scale if cooldown_scale is not None else 1.0))
                self.duration_scale.variable.set(float(duration_scale if duration_scale is not None else 1.0))
                self.strength_scale.variable.set(float(strength_scale if strength_scale is not None else 1.0))
                self._set_words_text(self.names_text, settings.get("names", []))
                self._set_words_text(self.scolding_words_text, settings.get("scolding_words", []))
                self._set_words_text(self.forbidden_words_text, settings.get("forbidden_words", []))
        finally:
            self._suppress_callbacks = False

        self._update_profile_visibility()

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
