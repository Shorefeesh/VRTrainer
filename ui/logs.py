import tkinter as tk
from tkinter import ttk

from logic import services


class EventLogPanel(ttk.LabelFrame):
    """Top-level event log that stays visible regardless of tab."""

    def __init__(self, master, *, list_height: int = 6) -> None:
        super().__init__(master, text="Event log")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._events = tk.Listbox(self, height=list_height)
        self._events.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._events.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._events.configure(yscrollcommand=scrollbar.set)

        self._refresh()

    def _set_events(self, events: list[str]) -> None:
        self._events.delete(0, "end")
        for event in events:
            self._events.insert("end", event)

    def _refresh(self) -> None:
        try:
            details = services.get_server_session_details()
            events = details.get("events") or []
            self._set_events(events)
        except Exception:
            # UI should fail soft; missing events is not fatal.
            pass

        self.after(1500, self._refresh)


class WhisperLogPanel(ttk.LabelFrame):
    """Whisper transcript that follows the active runtime regardless of tab."""

    def __init__(self, master, *, list_height: int = 6) -> None:
        super().__init__(master, text="Whisper log")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._text = tk.Text(self, height=list_height, wrap="word", state="disabled")
        self._text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._text.configure(yscrollcommand=scrollbar.set)

        self._current_role: str | None = None
        self._current_session: str | None = None
        self._has_content = False

        self._reset_log(role=None)
        self._refresh()

    def _reset_log(self, role: str | None) -> None:
        self._has_content = False
        if role:
            placeholder = f"Waiting for {role} whisper input..."
        else:
            placeholder = "Whisper transcript will appear after starting a trainer or pet runtime."
        self._set_text(placeholder)

    def _set_text(self, text: str) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        if text:
            if not text.endswith("\n"):
                text += "\n"
            self._text.insert("end", text)
        self._text.configure(state="disabled")

    def _append_text(self, text: str) -> None:
        if not text:
            return

        if not self._has_content:
            self._set_text("")
            self._has_content = True

        self._text.configure(state="normal")
        self._text.insert("end", text + "\n")

        line_count = int(self._text.index("end-1c").split(".")[0])
        if line_count > 300:
            self._text.delete("1.0", f"{line_count - 300}.0")

        self._text.see("end")
        self._text.configure(state="disabled")

    def _refresh(self) -> None:
        try:
            details = services.get_server_session_details()
            role_raw = (details.get("role") or "").lower()
            role = role_raw if role_raw in {"trainer", "pet"} else None
            session_id = details.get("session_id") or None

            if role != self._current_role or session_id != self._current_session:
                self._current_role = role
                self._current_session = session_id
                self._reset_log(role)

            new_text = ""
            if role == "trainer" and services.is_running():
                new_text = services.get_whisper_log_text()
            elif role == "pet" and services.is_running():
                new_text = services.get_whisper_log_text()

            if new_text:
                self._append_text(new_text)
        except Exception:
            pass

        self.after(1000, self._refresh)
