from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from logic import services

from .shared import LabeledEntry, ScrollableFrame


class SessionTab(ScrollableFrame):
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

        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(1, weight=1)

        self._runtime_status_provider = runtime_status_provider or (lambda role: {})
        self._on_join_trainer = on_join_trainer
        self._on_join_pet = on_join_pet
        self._on_leave_session = on_leave_session
        self._on_pet_profile_selected = on_pet_profile_selected

        # Shared state -------------------------------------------------
        self.role_var = tk.StringVar(value="trainer")
        self.session_role_var = tk.StringVar(value="-")
        self.session_username_var = tk.StringVar(value="")
        self.session_id_var = tk.StringVar(value="")

        self._profile_options: list[str] = ["(no profile)"]
        self._pet_profile_vars: dict[str, tk.StringVar] = {}
        self._last_pet_roster: list[dict] = []
        self._last_assignments: dict[str, str] = {}
        self._last_participants: list[dict] = []
        self._last_stats_by_user: dict = {}
        self._roster_header_rendered = False
        self._roster_rows: dict[str, dict] = {}
        self._roster_empty_label: ttk.Label | None = None

        # Before-join layout ------------------------------------------
        setup = ttk.LabelFrame(self.container, text="Session setup")
        setup.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        setup.columnconfigure(0, weight=1)
        self._setup_frame = setup

        self.username_entry = LabeledEntry(setup, "Username")
        self.username_entry.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        role_row = ttk.Frame(setup)
        role_row.grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Label(role_row, text="Role:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Radiobutton(role_row, text="Trainer", value="trainer", variable=self.role_var).grid(row=0, column=1, padx=(0, 12))
        ttk.Radiobutton(role_row, text="Pet", value="pet", variable=self.role_var).grid(row=0, column=2)

        buttons = ttk.Frame(setup)
        buttons.grid(row=2, column=0, sticky="w")
        self.start_btn = ttk.Button(buttons, text="Start Session", command=self._start_session)
        self.start_btn.grid(row=0, column=0, padx=(0, 8))
        self.join_btn = ttk.Button(buttons, text="Join Session", command=self._open_join_dialog)
        self.join_btn.grid(row=0, column=1)

        # After-join layout -------------------------------------------
        session = ttk.LabelFrame(self.container, text="Session")
        session.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        session.columnconfigure(0, weight=1)
        session.columnconfigure(1, weight=1)
        self.session_frame = session

        # Locked identity + role
        self.session_username_entry = LabeledEntry(session, "Username", state="readonly")
        self.session_username_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.session_username_entry.variable = self.session_username_var  # keep compatibility for bindings
        self.session_username_entry.entry.configure(textvariable=self.session_username_var)

        role_display = ttk.Frame(session)
        role_display.grid(row=0, column=1, sticky="e")
        ttk.Label(role_display, text="Role:").grid(row=0, column=0, sticky="e", padx=(0, 6))
        self.session_role_label = ttk.Label(role_display, textvariable=self.session_role_var)
        self.session_role_label.grid(row=0, column=1, sticky="e")

        ttk.Label(session, text="Session ID:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.session_id_entry = ttk.Entry(session, textvariable=self.session_id_var, state="readonly")
        self.session_id_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))

        self.leave_btn = ttk.Button(session, text="Leave Session", command=self._leave_session)
        self.leave_btn.grid(row=2, column=0, sticky="w", pady=(6, 0))

        roster_frame = ttk.LabelFrame(session, text="Session roster")
        roster_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        roster_frame.columnconfigure(0, weight=1)
        roster_frame.rowconfigure(0, weight=1)

        self.roster_table = ttk.Frame(roster_frame)
        self.roster_table.grid(row=0, column=0, sticky="nsew")
        for idx, weight in enumerate((1, 0, 2, 1, 1, 1)):
            self.roster_table.columnconfigure(idx, weight=weight)

        # Join dialog state ------------------------------------------
        self._join_dialog: tk.Toplevel | None = None
        self._join_session_var = tk.StringVar()
        self._join_error_var = tk.StringVar()

        # Kick off refresh loop
        self._set_join_state(in_session=False)
        self._refresh_details()

    # Button handlers -------------------------------------------------
    def _start_session(self) -> None:
        role = (self.role_var.get() or "trainer").lower()
        username = self.username_entry.variable.get().strip() or None
        details = services.start_server_session(session_label=None, username=username, role=role)
        self._update_from_details(details)
        if role == "trainer" and self._on_join_trainer is not None:
            self._on_join_trainer()
        elif role == "pet" and self._on_join_pet is not None:
            self._on_join_pet()

    def _open_join_dialog(self) -> None:
        if self._join_dialog is not None:
            try:
                self._join_dialog.lift()
                return
            except Exception:
                self._join_dialog = None

        dialog = tk.Toplevel(self)
        dialog.title("Join session")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(False, False)
        self._join_dialog = dialog

        ttk.Label(dialog, text="Enter session ID:").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        entry = ttk.Entry(dialog, textvariable=self._join_session_var)
        entry.grid(row=1, column=0, sticky="ew", padx=10)
        entry.focus_set()

        self._join_error_var.set("")
        error_label = ttk.Label(dialog, textvariable=self._join_error_var, foreground="red")
        error_label.grid(row=2, column=0, sticky="w", padx=10, pady=(4, 0))

        buttons = ttk.Frame(dialog)
        buttons.grid(row=3, column=0, sticky="e", padx=10, pady=(8, 10))
        ttk.Button(buttons, text="Back", command=self._close_join_dialog).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Join", command=self._join_session).grid(row=0, column=1)

        dialog.columnconfigure(0, weight=1)

    def _close_join_dialog(self) -> None:
        if self._join_dialog is None:
            return
        try:
            self._join_dialog.destroy()
        finally:
            self._join_dialog = None
            self._join_error_var.set("")
            self._join_session_var.set("")

    def _join_session(self) -> None:
        session_id = (self._join_session_var.get() or "").strip()
        if not session_id:
            self._join_error_var.set("Invalid session ID")
            return

        role = (self.role_var.get() or "trainer").lower()
        username = self.username_entry.variable.get().strip() or None

        details = services.join_server_session(session_id=session_id, username=username, role=role)
        self._update_from_details(details)

        if details.get("session_id"):
            self._close_join_dialog()
            if role == "trainer" and self._on_join_trainer is not None:
                self._on_join_trainer()
            elif role == "pet" and self._on_join_pet is not None:
                self._on_join_pet()
            return

        if not details.get("connected"):
            self._join_error_var.set("No connection to server")
        else:
            self._join_error_var.set("Invalid session ID")

    def _leave_session(self) -> None:
        details = services.leave_server_session()
        self._update_from_details(details)
        # Ensure we always return to the pre-join layout even if the next
        # refresh hasn't landed yet (e.g. network hiccup).
        self._set_join_state(False)
        if self._on_leave_session is not None:
            self._on_leave_session()

    # Details + rendering --------------------------------------------
    def _refresh_details(self) -> None:
        details = services.get_server_session_details()
        self._update_from_details(details)
        self.after(1500, self._refresh_details)

    def _update_from_details(self, details: dict) -> None:
        session_id = details.get("session_id") or ""
        state = (details.get("state") or "idle").lower()

        in_session = bool(session_id) and state not in {"idle", "left"}
        self._set_join_state(in_session)

        # Mirror username between setup + session views.
        username = details.get("username") or self.username_entry.variable.get()
        if not self.username_entry.variable.get().strip():
            self.username_entry.variable.set(username)
        self.session_username_var.set(username)

        role = (details.get("role") or "-")
        if in_session:
            self.role_var.set(role)
            self.session_role_var.set(role.capitalize())
        else:
            self.session_role_var.set("-")

        self.session_id_var.set(session_id)

        participants = details.get("session_participants") or details.get("session_users") or []
        stats_by_user = details.get("stats_by_user") or {}
        local_username = details.get("username")
        local_role = details.get("role")

        # Track pet roster + assignments for profile selectors.
        self._last_pet_roster = details.get("session_pets") or []
        self._last_assignments = details.get("pet_profile_assignments") or {}
        self._last_participants = participants
        self._last_stats_by_user = stats_by_user

        self._render_roster(participants, stats_by_user, local_username, local_role)

    def _set_join_state(self, in_session: bool) -> None:
        """Toggle which section of the UI is visible."""
        if in_session:
            # Hide setup, show session details.
            self.container.grid_rowconfigure(0, minsize=0, weight=0)
            self.container.grid_rowconfigure(1, weight=1)
            self._setup_frame.grid_remove()
            self.session_frame.grid()
            self.leave_btn.configure(state="normal")
        else:
            self.container.grid_rowconfigure(0, weight=1, minsize=0)
            self.container.grid_rowconfigure(1, weight=0)
            self._setup_frame.grid()
            self.session_frame.grid_remove()
            self.leave_btn.configure(state="disabled")

    # Pet roster + profile assignment helpers -----------------------
    def set_profile_options(self, profiles: list[str]) -> None:
        """Update available trainer profiles for per-pet assignment."""

        options = ["(no profile)", *sorted(profiles)]
        self._profile_options = options
        self._render_roster(
            self._last_participants,
            self._last_stats_by_user,
            self.session_username_var.get(),
            self.role_var.get(),
        )

    def _render_roster(
        self,
        participants: list[dict],
        stats_by_user: dict,
        local_username: str | None,
        local_role: str | None,
    ) -> None:
        """Build the session roster table with live status + profile selectors."""

        participants = participants or []
        role_lower = (local_role or "").lower()
        assignments = self._last_assignments or {}

        # Render table header once.
        if not self._roster_header_rendered:
            headers = ["User", "Role", "VRChat OSC", "PiShock", "Whisper", "Profile"]
            for col, header in enumerate(headers):
                ttk.Label(self.roster_table, text=header, font=("TkDefaultFont", 9, "bold")).grid(
                    row=0, column=col, sticky="w", padx=(0, 6), pady=(0, 4)
                )
            self._roster_header_rendered = True

        # Empty state handling.
        if not participants:
            self._destroy_roster_rows()
            if self._roster_empty_label is None:
                self._roster_empty_label = ttk.Label(self.roster_table, text="No users in session")
                self._roster_empty_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
            return
        if self._roster_empty_label is not None:
            self._roster_empty_label.destroy()
            self._roster_empty_label = None

        desired_keys: list[str] = []
        for row_index, user in enumerate(participants, start=1):
            username = user.get("label") or user.get("username") or "-"
            role_raw = (user.get("role") or "").lower()
            role = "trainer" if role_raw == "leader" else "pet" if role_raw == "follower" else (role_raw or "-")
            user_status = user.get("last_status") or {}

            session_stats = stats_by_user.get(username) or []
            latest_status = {}
            for entry in reversed(session_stats):
                if entry.get("kind") == "status":
                    latest_status = entry
                    break

            status_overrides = {}
            if username == local_username:
                status_overrides = self._runtime_status_provider(local_role)

            osc_status = (
                status_overrides.get("osc_details")
                or user_status.get("osc_details")
                or latest_status.get("osc_details")
                or status_overrides.get("osc")
                or user_status.get("osc")
                or latest_status.get("osc")
                or "-"
            )
            pishock_status = status_overrides.get("pishock") or user_status.get("pishock") or latest_status.get("pishock") or "-"
            whisper_status = status_overrides.get("whisper") or user_status.get("whisper") or latest_status.get("whisper") or "-"

            key = str(user.get("client_uuid") or username or row_index)
            desired_keys.append(key)
            existing = self._roster_rows.get(key)
            is_pet_row = role_lower == "trainer" and role == "pet"

            row_payload = {
                "username": username,
                "role": role,
                "osc": osc_status,
                "pishock": pishock_status,
                "whisper": whisper_status,
                "assignment": assignments.get(str(user.get("client_uuid") or "")) or "(no profile)",
                "is_pet_row": is_pet_row,
            }

            if existing is None or existing.get("is_pet_row") != is_pet_row:
                self._destroy_roster_row(key)
                self._create_roster_row(key, row_index, row_payload)
            else:
                self._update_roster_row(key, row_index, row_payload)

        # Destroy rows no longer present.
        for key in list(self._roster_rows.keys()):
            if key not in desired_keys:
                self._destroy_roster_row(key)

    def _create_roster_row(self, key: str, row_index: int, payload: dict) -> None:
        """Build a roster row for a user and store its widgets."""

        widgets: dict[str, tk.Widget] = {}

        widgets["username"] = ttk.Label(self.roster_table, text=payload["username"])
        widgets["username"].grid(row=row_index, column=0, sticky="w", padx=(0, 6), pady=2)

        widgets["role"] = ttk.Label(self.roster_table, text=payload["role"].title())
        widgets["role"].grid(row=row_index, column=1, sticky="w", padx=(0, 6))

        widgets["osc"] = ttk.Label(self.roster_table, text=payload["osc"])
        widgets["osc"].grid(row=row_index, column=2, sticky="w", padx=(0, 6))

        widgets["pishock"] = ttk.Label(self.roster_table, text=payload["pishock"])
        widgets["pishock"].grid(row=row_index, column=3, sticky="w", padx=(0, 6))

        widgets["whisper"] = ttk.Label(self.roster_table, text=payload["whisper"])
        widgets["whisper"].grid(row=row_index, column=4, sticky="w", padx=(0, 6))

        profile_widget: tk.Widget
        profile_var: tk.StringVar | None = None
        if payload["is_pet_row"]:
            profile_var = tk.StringVar(value=payload["assignment"])
            profile_widget = ttk.Combobox(
                self.roster_table,
                textvariable=profile_var,
                values=self._profile_options,
                state="readonly",
                width=18,
            )
            profile_widget.grid(row=row_index, column=5, sticky="ew", padx=(0, 6))
            profile_widget.bind(
                "<<ComboboxSelected>>",
                lambda _evt, pid=key, v=profile_var: self._on_pet_profile_change(pid, v.get()),
            )
            if profile_var.get() not in self._profile_options:
                profile_var.set("(no profile)")
                self._on_pet_profile_change(key, "(no profile)")
            self._pet_profile_vars[key] = profile_var
        else:
            profile_text = "Not used" if payload["role"] == "trainer" else payload["assignment"] or "-"
            profile_widget = ttk.Label(self.roster_table, text=profile_text)
            profile_widget.grid(row=row_index, column=5, sticky="w", padx=(0, 6))

        self._roster_rows[key] = {
            "widgets": widgets,
            "profile_widget": profile_widget,
            "profile_var": profile_var,
            "is_pet_row": payload["is_pet_row"],
        }

    def _update_roster_row(self, key: str, row_index: int, payload: dict) -> None:
        """Update an existing roster row without tearing down focused widgets."""

        row = self._roster_rows.get(key)
        if row is None:
            self._create_roster_row(key, row_index, payload)
            return

        widgets = row["widgets"]
        # Update text fields only if they changed to avoid churn.
        if widgets["username"].cget("text") != payload["username"]:
            widgets["username"].configure(text=payload["username"])
        if widgets["role"].cget("text").lower() != payload["role"]:
            widgets["role"].configure(text=payload["role"].title())
        if widgets["osc"].cget("text") != payload["osc"]:
            widgets["osc"].configure(text=payload["osc"])
        if widgets["pishock"].cget("text") != payload["pishock"]:
            widgets["pishock"].configure(text=payload["pishock"])
        if widgets["whisper"].cget("text") != payload["whisper"]:
            widgets["whisper"].configure(text=payload["whisper"])

        # Keep row ordering in sync with participant ordering.
        for widget in widgets.values():
            widget.grid_configure(row=row_index)

        profile_widget = row["profile_widget"]
        if row["is_pet_row"]:
            var = row["profile_var"]
            desired_assignment = payload["assignment"]
            if desired_assignment not in self._profile_options:
                desired_assignment = "(no profile)"
            if var is not None and var.get() != desired_assignment:
                # Preserve selection while keeping assignment in sync.
                var.set(desired_assignment)
                if desired_assignment == "(no profile)" and payload["assignment"] != "(no profile)":
                    self._on_pet_profile_change(key, "(no profile)")
            if tuple(profile_widget.cget("values")) != tuple(self._profile_options):
                profile_widget.configure(values=self._profile_options)
            profile_widget.grid_configure(row=row_index)
        else:
            desired_text = "Not used" if payload["role"] == "trainer" else payload["assignment"] or "-"
            if profile_widget.cget("text") != desired_text:
                profile_widget.configure(text=desired_text)
            profile_widget.grid_configure(row=row_index)

    def _destroy_roster_rows(self) -> None:
        """Remove all roster rows (not the header)."""
        for key in list(self._roster_rows.keys()):
            self._destroy_roster_row(key)

    def _destroy_roster_row(self, key: str) -> None:
        """Destroy widgets for a single roster row."""
        row = self._roster_rows.pop(key, None)
        if row is None:
            return
        for widget in row["widgets"].values():
            widget.destroy()
        if row["profile_widget"] is not None:
            row["profile_widget"].destroy()
        if key in self._pet_profile_vars:
            self._pet_profile_vars.pop(key, None)

    def _on_pet_profile_change(self, pet_id: str, selection: str) -> None:
        profile_name = selection if selection and selection != "(no profile)" else None
        if self._on_pet_profile_selected is not None:
            self._on_pet_profile_selected(pet_id, profile_name)
