from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from logic import services

from .shared import LabeledEntry, ScrollableFrame, StatusIndicator


class ServerTab(ttk.Frame):
    """Tab that surfaces basic server session controls."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)

        self.columnconfigure(0, weight=1)

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

        self.session_label_entry = LabeledEntry(actions, "New session label")
        self.session_label_entry.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        start_btn = ttk.Button(actions, text="Start session", command=self._start_session)
        start_btn.grid(row=1, column=1, padx=(8, 0))

        self.session_code_entry = LabeledEntry(actions, "Join session code")
        self.session_code_entry.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        join_btn = ttk.Button(actions, text="Join session", command=self._join_session)
        join_btn.grid(row=2, column=1, padx=(8, 0))

        leave_btn = ttk.Button(actions, text="Leave session", command=self._leave_session)
        leave_btn.grid(row=3, column=0, sticky="w", pady=(4, 0))

        details = ttk.LabelFrame(self, text="Session details")
        details.grid(row=2, column=0, sticky="nsew", padx=10, pady=6)
        details.columnconfigure(1, weight=1)

        ttk.Label(details, text="Role:").grid(row=0, column=0, sticky="w")
        ttk.Label(details, text="State:").grid(row=1, column=0, sticky="w")
        ttk.Label(details, text="Session ID:").grid(row=2, column=0, sticky="w")

        self.role_var = tk.StringVar(value="-")
        self.state_var = tk.StringVar(value="idle")
        self.session_id_var = tk.StringVar(value="-")

        ttk.Label(details, textvariable=self.role_var).grid(row=0, column=1, sticky="w")
        ttk.Label(details, textvariable=self.state_var).grid(row=1, column=1, sticky="w")
        ttk.Label(details, textvariable=self.session_id_var).grid(row=2, column=1, sticky="w")

        ttk.Label(details, text="Users in session:").grid(row=3, column=0, sticky="w", pady=(8, 0))

        users_frame = ttk.Frame(details)
        users_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(0, 4))
        details.rowconfigure(4, weight=1)

        self.users_tree = ttk.Treeview(
            users_frame,
            columns=("username", "status"),
            show="headings",
            height=4,
        )
        self.users_tree.heading("username", text="User")
        self.users_tree.heading("status", text="Status")
        self.users_tree.column("username", anchor="w", width=160)
        self.users_tree.column("status", anchor="center", width=80)

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
    def _start_session(self) -> None:
        label = self.session_label_entry.variable.get().strip() or None
        username = self.username_entry.variable.get().strip() or None
        details = services.start_server_session(session_label=label, username=username)
        self._display_message("Started a new session.")
        self._update_from_details(details)

    def _join_session(self) -> None:
        try:
            code = self.session_code_entry.variable.get()
            username = self.username_entry.variable.get().strip() or None
            details = services.join_server_session(session_id=code, username=username)
            self._display_message("Joined existing session.")
            self._update_from_details(details)
        except ValueError as exc:
            self._display_message(str(exc), error=True)

    def _leave_session(self) -> None:
        details = services.leave_server_session()
        self._display_message("Left the current session.")
        self._update_from_details(details)

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

        session_id = details.get("session_id") or "-"
        self.session_id_var.set(session_id)

        if not self.username_entry.variable.get().strip():
            username = details.get("username") or ""
            self.username_entry.variable.set(username)

        users = details.get("session_users") or []
        self.users_tree.delete(*self.users_tree.get_children())
        if users:
            for user in users:
                username = user.get("username") or "-"
                status = user.get("status") or "pending"
                self.users_tree.insert("", "end", values=(username, status))
        else:
            self.users_tree.insert("", "end", values=("No users", "-"))

        events = details.get("events") or []
        self.events_list.delete(0, "end")
        for event in events:
            self.events_list.insert("end", event)

    def _display_message(self, message: str, *, error: bool = False) -> None:
        self.message_var.set(message)
        colour = "red" if error else "gray"
        self.message_label.configure(foreground=colour)
