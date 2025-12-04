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
    ) -> None:
        super().__init__(parent)

        self.columnconfigure(0, weight=1)

        self._runtime_status_provider = runtime_status_provider or (lambda role: {})
        self._on_join_trainer = on_join_trainer
        self._on_join_pet = on_join_pet
        self._on_leave_session = on_leave_session

        status_frame = ttk.LabelFrame(self, text="Connection")
        status_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        status_frame.columnconfigure(0, weight=1)

        self.connection_status = StatusIndicator(status_frame, "Server")
        self.connection_status.grid(row=0, column=0, sticky="w")

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

        log_frame = ScrollableFrame(details)
        log_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        details.rowconfigure(5, weight=1)

        ttk.Label(log_frame.container, text="Recent events:").grid(row=0, column=0, sticky="w")
        self.events_list = tk.Listbox(log_frame.container, height=6)
        self.events_list.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        log_frame.container.columnconfigure(0, weight=1)
        log_frame.container.rowconfigure(1, weight=1)

        self.message_var = tk.StringVar(value="Control the server session from this tab.")
        self.message_label = ttk.Label(self, textvariable=self.message_var, foreground="gray")
        self.message_label.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 10))

        self._refresh_details()

    # Button handlers -------------------------------------------------
    def _start_session(self, role: str) -> None:
        username = self.username_entry.variable.get().strip() or None
        details = services.start_server_session(session_label=None, username=username, role=role)
        self._display_message(f"Started a new session as {role}.")
        self._update_from_details(details)
        if role == "trainer" and self._on_join_trainer is not None:
            self._on_join_trainer()
        elif role == "pet" and self._on_join_pet is not None:
            self._on_join_pet()

    def _prompt_join(self, role: str) -> None:
        session_id = simpledialog.askstring("Join session", "Enter session ID:", parent=self.winfo_toplevel())
        if session_id is None:
            return
        try:
            username = self.username_entry.variable.get().strip() or None
            details = services.join_server_session(session_id=session_id, username=username, role=role)
            self._display_message(f"Joined as {role}.")
            self._update_from_details(details)
            if role == "trainer" and self._on_join_trainer is not None:
                self._on_join_trainer()
            elif role == "pet" and self._on_join_pet is not None:
                self._on_join_pet()
        except ValueError as exc:
            self._display_message(str(exc), error=True)

    def _leave_session(self) -> None:
        details = services.leave_server_session()
        self._display_message("Left the current session.")
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
        else:
            self.connection_status.set_status("Disconnected", "red")

        self.role_var.set(details.get("role") or "-")
        self.state_var.set(details.get("state") or "idle")

        session_id = details.get("session_id")
        self.session_id_var.set(session_id or "")

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

    def _display_message(self, message: str, *, error: bool = False) -> None:
        self.message_var.set(message)
        colour = "red" if error else "gray"
        self.message_label.configure(foreground=colour)

    def _set_session_controls_enabled(self, enabled: bool) -> None:
        """Toggle controls that should not change mid-session."""
        state = "normal" if enabled else "disabled"
        self.username_entry.entry.configure(state=state)
        self.start_btn_trainer.configure(state=state)
        self.start_btn_pet.configure(state=state)
        self.join_btn_trainer.configure(state=state)
        self.join_btn_pet.configure(state=state)
