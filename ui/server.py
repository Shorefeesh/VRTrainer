from __future__ import annotations

import tkinter as tk
from tkinter import ttk, simpledialog

from logic import services

from .shared import LabeledEntry, ScrollableFrame, StatusIndicator


class ServerTab(ttk.Frame):
    """Tab that surfaces basic server session controls."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        runtime_status_provider=None,
        on_join_trainer=None,
        on_join_pet=None,
        on_leave_session=None,
        on_pet_profile_selected=None,
    ) -> None:
        super().__init__(parent)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)

        self._runtime_status_provider = runtime_status_provider or (lambda role: {})
        self._on_join_trainer = on_join_trainer
        self._on_join_pet = on_join_pet
        self._on_leave_session = on_leave_session
        self._on_pet_profile_selected = on_pet_profile_selected

        status_frame = ttk.LabelFrame(self, text="Connection")
        status_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        status_frame.columnconfigure(0, weight=1)

        self.connection_status = StatusIndicator(status_frame, "Server")
        self.connection_status.grid(row=0, column=0, sticky="w")

        self.reconnect_btn = ttk.Button(status_frame, text="Reconnect", command=self._reconnect_server)
        self.reconnect_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))

        actions = ttk.LabelFrame(self, text="Session actions")
        actions.grid(row=1, column=0, sticky="ew", padx=10, pady=6)
        actions.columnconfigure(0, weight=1)

        self.username_entry = LabeledEntry(actions, "Username")
        self.username_entry.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.start_btn_trainer = ttk.Button(
            actions,
            text="Start as Trainer",
            command=lambda: self._start_session("trainer"),
        )
        self.start_btn_trainer.grid(row=1, column=0, sticky="w", pady=(0, 4))

        self.start_btn_pet = ttk.Button(actions, text="Start as Pet", command=lambda: self._start_session("pet"))
        self.start_btn_pet.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(0, 4))

        self.join_btn_trainer = ttk.Button(actions, text="Join as Trainer", command=lambda: self._prompt_join("trainer"))
        self.join_btn_trainer.grid(row=2, column=0, sticky="w", pady=(0, 4))

        self.join_btn_pet = ttk.Button(actions, text="Join as Pet", command=lambda: self._prompt_join("pet"))
        self.join_btn_pet.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(0, 4))

        self.leave_btn = ttk.Button(actions, text="Leave session", command=self._leave_session)
        self.leave_btn.grid(row=3, column=0, sticky="w", pady=(4, 0))

        details = ttk.LabelFrame(self, text="Session details")
        details.grid(row=2, column=0, sticky="nsew", padx=10, pady=6)
        details.columnconfigure(1, weight=1)
        self.details_frame = details

        ttk.Label(details, text="Role:").grid(row=0, column=0, sticky="w")
        ttk.Label(details, text="State:").grid(row=1, column=0, sticky="w")
        ttk.Label(details, text="Session ID:").grid(row=2, column=0, sticky="w")

        self.role_var = tk.StringVar(value="-")
        self.state_var = tk.StringVar(value="idle")
        self.session_id_var = tk.StringVar(value="-")

        ttk.Label(details, textvariable=self.role_var).grid(row=0, column=1, sticky="w")
        ttk.Label(details, textvariable=self.state_var).grid(row=1, column=1, sticky="w")
        self.session_id_entry = ttk.Entry(details, textvariable=self.session_id_var, state="readonly")
        self.session_id_entry.grid(row=2, column=1, sticky="ew")

        ttk.Label(details, text="Users in session:").grid(row=3, column=0, sticky="w", pady=(8, 0))

        users_frame = ttk.Frame(details)
        users_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(0, 4))
        details.rowconfigure(4, weight=1)

        self.users_tree = ttk.Treeview(
            users_frame,
            columns=("username", "role", "osc", "pishock", "whisper"),
            show="headings",
            height=4,
        )
        self.users_tree.heading("username", text="User")
        self.users_tree.heading("role", text="Role")
        self.users_tree.heading("osc", text="VRChat OSC")
        self.users_tree.heading("pishock", text="PiShock")
        self.users_tree.heading("whisper", text="Whisper")

        self.users_tree.column("username", anchor="w", width=150)
        self.users_tree.column("role", anchor="center", width=70)
        self.users_tree.column("osc", anchor="w", width=150)
        self.users_tree.column("pishock", anchor="w", width=110)
        self.users_tree.column("whisper", anchor="w", width=130)

        users_scrollbar = ttk.Scrollbar(users_frame, orient="vertical", command=self.users_tree.yview)
        self.users_tree.configure(yscrollcommand=users_scrollbar.set)
        self.users_tree.grid(row=0, column=0, sticky="nsew")
        users_scrollbar.grid(row=0, column=1, sticky="ns")
        users_frame.columnconfigure(0, weight=1)
        users_frame.rowconfigure(0, weight=1)

        ttk.Label(details, text="Pet profiles:").grid(row=5, column=0, sticky="w", pady=(4, 0))
        pet_profiles_frame = ScrollableFrame(details)
        pet_profiles_frame.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(0, 4))
        self.pet_profiles_container = pet_profiles_frame.container

        log_frame = ScrollableFrame(details)
        log_frame.grid(row=7, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        details.rowconfigure(7, weight=1)

        ttk.Label(log_frame.container, text="Recent events:").grid(row=0, column=0, sticky="w")
        self.events_list = tk.Listbox(log_frame.container, height=6)
        self.events_list.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        log_frame.container.columnconfigure(0, weight=1)
        log_frame.container.rowconfigure(1, weight=1)

        # Whisper transcript log anchored at the bottom of the tab.
        self._whisper_log_role: str | None = None
        self._whisper_session_id: str | None = None
        self._whisper_has_content = False

        whisper_frame = ttk.LabelFrame(self, text="Whisper log")
        whisper_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        whisper_frame.columnconfigure(0, weight=1)
        whisper_frame.rowconfigure(0, weight=1)

        self.whisper_text = tk.Text(whisper_frame, height=6, wrap="word", state="disabled")
        self.whisper_text.grid(row=0, column=0, sticky="nsew")

        whisper_scrollbar = ttk.Scrollbar(whisper_frame, orient="vertical", command=self.whisper_text.yview)
        whisper_scrollbar.grid(row=0, column=1, sticky="ns")
        self.whisper_text.configure(yscrollcommand=whisper_scrollbar.set)

        self._set_whisper_text("Whisper transcript will appear here when the local runtime is active.")

        # Per-pet profile assignment UI state.
        self._profile_options: list[str] = ["(no profile)"]
        self._pet_profile_vars: dict[str, tk.StringVar] = {}
        self._last_pet_roster: list[dict] = []
        self._last_assignments: dict[str, str] = {}

        self._refresh_details()
        self._refresh_whisper_log()

    # Button handlers -------------------------------------------------
    def _start_session(self, role: str) -> None:
        username = self.username_entry.variable.get().strip() or None
        details = services.start_server_session(session_label=None, username=username, role=role)
        self._update_from_details(details)
        if role == "trainer" and self._on_join_trainer is not None:
            self._on_join_trainer()
        elif role == "pet" and self._on_join_pet is not None:
            self._on_join_pet()

    def _prompt_join(self, role: str) -> None:
        session_id = simpledialog.askstring("Join session", "Enter session ID:", parent=self.winfo_toplevel())
        if session_id is None:
            return
        username = self.username_entry.variable.get().strip() or None
        details = services.join_server_session(session_id=session_id, username=username, role=role)
        self._update_from_details(details)
        if role == "trainer" and self._on_join_trainer is not None:
            self._on_join_trainer()
        elif role == "pet" and self._on_join_pet is not None:
            self._on_join_pet()

    def _leave_session(self) -> None:
        details = services.leave_server_session()
        self._update_from_details(details)
        if self._on_leave_session is not None:
            self._on_leave_session()

    # Details + rendering --------------------------------------------
    def _refresh_details(self) -> None:
        details = services.get_server_session_details()
        self._update_from_details(details)
        self.after(1500, self._refresh_details)

    def _update_from_details(self, details: dict) -> None:
        connected = bool(details.get("connected"))
        if connected:
            self.connection_status.set_status("Connected", "green")
            self.reconnect_btn.configure(state="disabled")
        else:
            self.connection_status.set_status("Disconnected", "red")
            self.reconnect_btn.configure(state="normal")

        self.role_var.set(details.get("role") or "-")
        self.state_var.set(details.get("state") or "idle")

        session_id = details.get("session_id")
        self.session_id_var.set(session_id or "")
        self._update_whisper_context(details.get("role"), session_id)

        if not self.username_entry.variable.get().strip():
            username = details.get("username") or ""
            self.username_entry.variable.set(username)

        users = details.get("session_users") or []
        stats_by_user = details.get("stats_by_user") or {}
        local_username = details.get("username")
        local_role = details.get("role")
        self.users_tree.delete(*self.users_tree.get_children())
        if users:
            for user in users:
                username = user.get("username") or "-"
                role = user.get("status") or "pending"
                session_stats = stats_by_user.get(username) or []
                latest_status = {}
                for entry in reversed(session_stats):
                    if entry.get("kind") == "status":
                        latest_status = entry
                        break
                status_overrides = {}
                if username == local_username:
                    status_overrides = self._runtime_status_provider(local_role)

                osc_status = status_overrides.get("osc") or latest_status.get("osc") or "-"
                pishock_status = status_overrides.get("pishock") or latest_status.get("pishock") or "-"
                whisper_status = status_overrides.get("whisper") or latest_status.get("whisper") or "-"

                self.users_tree.insert(
                    "",
                    "end",
                    values=(username, role, osc_status, pishock_status, whisper_status),
                )
        else:
            self.users_tree.insert("", "end", values=("No users", "-", "-", "-", "-"))

        events = details.get("events") or []
        self.events_list.delete(0, "end")
        for event in events:
            self.events_list.insert("end", event)

        role_lower = (details.get("role") or "").lower()
        if role_lower == "trainer":
            pets = details.get("session_pets") or []
            assignments = details.get("pet_profile_assignments") or {}
            self._last_pet_roster = pets
            self._last_assignments = assignments
            self._render_pet_profiles(pets, assignments)
        else:
            self._last_pet_roster = []
            self._last_assignments = {}
            self._render_pet_profiles([], {})

        in_session = bool(session_id)
        if in_session:
            if not self.details_frame.winfo_ismapped():
                self.details_frame.grid()
            if not self.leave_btn.winfo_ismapped():
                self.leave_btn.grid()
        else:
            if self.details_frame.winfo_ismapped():
                self.details_frame.grid_remove()
            if self.leave_btn.winfo_ismapped():
                self.leave_btn.grid_remove()
        self._set_session_controls_enabled(not in_session)

    def _update_whisper_context(self, role: str | None, session_id: str | None) -> None:
        """Reset whisper log when the active role or session changes."""
        role_value = role if role in {"trainer", "pet"} else None
        session_value = session_id or None

        if role_value == self._whisper_log_role and session_value == self._whisper_session_id:
            return

        self._reset_whisper_log(role_value, session_value)

    def _reset_whisper_log(self, role: str | None, session_id: str | None) -> None:
        self._whisper_log_role = role
        self._whisper_session_id = session_id
        self._whisper_has_content = False

        if role:
            message = f"Waiting for {role} whisper input..."
        else:
            message = "Whisper transcript will appear after starting a trainer or pet runtime."
        self._set_whisper_text(message)

    def _set_whisper_text(self, text: str) -> None:
        self.whisper_text.configure(state="normal")
        self.whisper_text.delete("1.0", "end")
        if text:
            if not text.endswith("\n"):
                text += "\n"
            self.whisper_text.insert("end", text)
        self.whisper_text.configure(state="disabled")

    def _append_whisper_text(self, text: str) -> None:
        if not text:
            return

        if not self._whisper_has_content:
            self._set_whisper_text("")
            self._whisper_has_content = True

        self.whisper_text.configure(state="normal")
        self.whisper_text.insert("end", text + "\n")

        # Keep memory usage bounded by trimming old lines.
        line_count = int(self.whisper_text.index("end-1c").split(".")[0])
        if line_count > 300:
            self.whisper_text.delete("1.0", f"{line_count - 300}.0")

        self.whisper_text.see("end")
        self.whisper_text.configure(state="disabled")

    def _refresh_whisper_log(self) -> None:
        try:
            role = (self.role_var.get() or "").lower()
            role_value = role if role in {"trainer", "pet"} else None
            session_id = self.session_id_var.get() or None

            # In case the server details have not refreshed yet.
            if role_value != self._whisper_log_role or session_id != self._whisper_session_id:
                self._reset_whisper_log(role_value, session_id)

            new_text = ""
            if role_value == "trainer" and services.is_trainer_running():
                new_text = services.get_trainer_whisper_log_text()
            elif role_value == "pet" and services.is_pet_running():
                new_text = services.get_pet_whisper_log_text()

            if new_text:
                self._append_whisper_text(new_text)
        except Exception:
            # Fail-soft: UI updates should not crash on runtime errors.
            pass

        self.after(1000, self._refresh_whisper_log)

    def _set_session_controls_enabled(self, enabled: bool) -> None:
        """Toggle controls that should not change mid-session."""
        state = "normal" if enabled else "disabled"
        self.username_entry.entry.configure(state=state)
        self.start_btn_trainer.configure(state=state)
        self.start_btn_pet.configure(state=state)
        self.join_btn_trainer.configure(state=state)
        self.join_btn_pet.configure(state=state)

    def _reconnect_server(self) -> None:
        """Attempt to reconnect to the remote server when offline."""

        role = (self.role_var.get() or "trainer").lower()
        details = services.reconnect_server(role=role if role in {"trainer", "pet"} else None)
        self._update_from_details(details)

    # Pet profile assignment helpers ----------------------------------
    def set_profile_options(self, profiles: list[str]) -> None:
        """Update available trainer profiles for per-pet assignment."""

        options = ["(no profile)", *sorted(profiles)]
        self._profile_options = options
        # Re-render to apply updated option lists while preserving selections.
        self._render_pet_profiles(self._last_pet_roster, self._last_assignments)

    def _render_pet_profiles(self, pets: list[dict], assignments: dict[str, str]) -> None:
        """Rebuild the per-pet profile selection rows."""

        for child in self.pet_profiles_container.winfo_children():
            child.destroy()

        if not pets:
            ttk.Label(self.pet_profiles_container, text="No pets in session").grid(row=0, column=0, sticky="w")
            self._pet_profile_vars.clear()
            return

        active_vars: dict[str, tk.StringVar] = {}
        for row, pet in enumerate(pets):
            pet_id = str(pet.get("client_uuid") or "")
            display = pet.get("label") or (pet_id[:8] if pet_id else "pet")
            ttk.Label(self.pet_profiles_container, text=display).grid(row=row, column=0, sticky="w", padx=(0, 6))

            current_assignment = assignments.get(pet_id) or "(no profile)"
            var = tk.StringVar(value=current_assignment)
            combo = ttk.Combobox(
                self.pet_profiles_container,
                textvariable=var,
                values=self._profile_options,
                state="readonly",
                width=24,
            )
            combo.grid(row=row, column=1, sticky="ew", pady=2)
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _evt, pid=pet_id, v=var: self._on_pet_profile_change(pid, v.get()),
            )

            # Ensure the selection reflects current options even if the profile was deleted.
            if var.get() not in self._profile_options:
                var.set("(no profile)")
                self._on_pet_profile_change(pet_id, "(no profile)")

            active_vars[pet_id] = var

        self._pet_profile_vars = active_vars
        self.pet_profiles_container.columnconfigure(1, weight=1)

    def _on_pet_profile_change(self, pet_id: str, selection: str) -> None:
        """Translate UI selection into a callback to the main app."""

        profile_name = selection if selection and selection != "(no profile)" else None
        if self._on_pet_profile_selected is not None:
            self._on_pet_profile_selected(pet_id, profile_name)
