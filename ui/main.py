import tkinter as tk
from tkinter import ttk, font

from config import load_config, save_config
from interfaces.audio_devices import list_input_devices
from logic import services
from logic import profile as trainer_profile

from .logs import EventLogPanel, WhisperLogPanel
from .trainer import TrainerTab
from .pet import PetTab
from .stats import StatsTab
from .session import SessionTab
from .status import ConnectionStatusPanel, format_osc_status, format_pishock_status


def create_root() -> tk.Tk:
    root = tk.Tk()
    root.title("VRTrainer")
    root.geometry("900x600")
    return root


def build_ui(root: tk.Tk) -> None:
    style = ttk.Style(root)
    tab_font = font.Font(root, family="TkDefaultFont", size=12, weight="bold")
    # Apply to all notebook tabs so label font is larger and width uniform.
    style.configure("TNotebook.Tab", font=tab_font, padding=(20, 10), width=12)

    # Load configuration once at startup.
    config = load_config()

    main_frame = ttk.Frame(root)
    main_frame.pack(fill="both", expand=True)
    main_frame.rowconfigure(0, weight=6)
    main_frame.rowconfigure(1, weight=0)
    main_frame.rowconfigure(2, weight=2)
    main_frame.rowconfigure(3, weight=3)
    main_frame.columnconfigure(0, weight=1)

    notebook = ttk.Notebook(main_frame)
    input_device_var = tk.StringVar(root)

    def _on_input_device_changed(*_) -> None:
        section = config.setdefault("settings", {})
        value = input_device_var.get()
        section["input_device"] = value or None
        save_config(config)

    input_device_var.trace_add("write", _on_input_device_changed)

    # Trainer tab --------------------------------------------------------
    def on_trainer_settings_changed(settings: dict) -> None:
        trainer_profile.update_profile_from_settings(config, settings)
        save_config(config)
        services.notify_profile_updated(settings)
        session_tab.set_profile_options(trainer_profile.list_profile_names(config))

    def on_trainer_profile_selected(profile_name: str) -> None:
        if not profile_name:
            trainer_profile.set_active_profile_name(config, None)
            save_config(config)
            return

        trainer_profile.set_active_profile_name(config, profile_name)
        current = trainer_profile.get_profile(config, profile_name)
        if current is None:
            current = trainer_profile.default_profile_settings(profile_name)
            trainer_profile.update_profile_from_settings(config, current)
        trainer_tab.apply_profile_settings(current)
        save_config(config)
        session_tab.set_profile_options(trainer_profile.list_profile_names(config))

    def on_trainer_profile_renamed(old_name: str, new_name: str) -> None:
        if trainer_profile.rename_profile(config, old_name, new_name):
            save_config(config)
            services.rename_profile_assignment(old_name, new_name)
            session_tab.set_profile_options(trainer_profile.list_profile_names(config))

    def on_trainer_profile_deleted(profile_name: str) -> None:
        if trainer_profile.delete_profile(config, profile_name):
            save_config(config)
            services.remove_profile_assignments(profile_name)
            session_tab.set_profile_options(trainer_profile.list_profile_names(config))

    trainer_tab = TrainerTab(
        notebook,
        on_settings_change=on_trainer_settings_changed,
        on_profile_selected=on_trainer_profile_selected,
        on_profile_renamed=on_trainer_profile_renamed,
        on_profile_deleted=on_trainer_profile_deleted,
        input_device_var=input_device_var,
    )

    # Populate trainer profiles from config.
    profiles = trainer_profile.list_profile_names(config)
    trainer_tab.set_profiles(profiles)

    active_profile = trainer_profile.get_active_profile_name(config)
    if active_profile:
        trainer_tab.profile_row.variable.set(active_profile)
        stored = trainer_profile.get_profile(config, active_profile)
        if stored:
            trainer_tab.apply_profile_settings(stored)

    # Pet tab ------------------------------------------------------------

    def on_pet_settings_changed(settings: dict) -> None:
        config["pet"] = dict(settings)
        save_config(config)

    pet_tab = PetTab(notebook, on_settings_change=on_pet_settings_changed, input_device_var=input_device_var)

    # Populate available input devices across all tabs.
    devices = list_input_devices()
    settings_conf = config.get("settings") or {}
    stored_device = settings_conf.get("input_device")

    display_devices = list(devices)
    if stored_device and stored_device not in display_devices:
        display_devices.append(stored_device)

    for tab in (trainer_tab, pet_tab):
        tab.set_input_devices(display_devices)

    if stored_device:
        input_device_var.set(stored_device)
    elif display_devices:
        input_device_var.set(display_devices[0])

    # Restore pet settings from config, if any.
    pet_settings_conf = config.get("pet") or {}
    if pet_settings_conf:
        pet_tab.apply_settings(pet_settings_conf)
    # Runtime orchestration now lives alongside session joins.

    def _start_trainer_runtime() -> None:
        trainer_settings = trainer_tab.collect_settings()
        input_device = trainer_tab.input_device
        services.start_trainer(trainer_settings, input_device)

    def _start_pet_runtime() -> None:
        pet_settings = pet_tab.collect_settings()
        input_device = pet_tab.input_device
        services.start_pet(pet_settings, input_device)

    def runtime_status_provider(role: str | None) -> dict[str, str]:
        running = services.is_running()
        osc_status = services.get_osc_status() if running else None
        pishock_status = services.get_pishock_status() if running else None
        whisper_status = services.get_whisper_backend() if running else "Stopped"
        osc_text = format_osc_status(role, osc_status) if running else "Stopped"

        status = {
            "osc": osc_text,
            "osc_details": osc_text,
            "pishock": format_pishock_status(pishock_status, running),
            "whisper": whisper_status,
        }
        username = services.get_server_username()
        if username:
            status["username"] = username

        services.publish_runtime_status(role, status)
        return status

    stats_tab = StatsTab(notebook)
    def on_pet_profile_selected(pet_client_id: str, profile_name: str | None) -> None:
        if not profile_name:
            services.assign_profile_to_pet(pet_client_id, None, None)
            return

        settings = trainer_profile.get_profile(config, profile_name)
        if settings is None:
            services.assign_profile_to_pet(pet_client_id, None, None)
            return
        services.assign_profile_to_pet(pet_client_id, profile_name, settings)

    session_tab = SessionTab(
        notebook,
        runtime_status_provider=runtime_status_provider,
        on_join_trainer=_start_trainer_runtime,
        on_join_pet=_start_pet_runtime,
        on_leave_session=services.stop_runtime,
        on_pet_profile_selected=on_pet_profile_selected,
    )
    session_tab.set_profile_options(trainer_profile.list_profile_names(config))

    # Persist session username across runs.
    session_config = config.setdefault("session", {})
    stored_username = session_config.get("username") or ""
    if stored_username:
        session_tab.username_entry.variable.set(stored_username)
        services.set_server_username(stored_username)

    def _on_server_username_changed(*_) -> None:
        username = session_tab.username_entry.variable.get().strip()
        session_config["username"] = username or None
        save_config(config)
        services.set_server_username(username or None)

    session_tab.username_entry.variable.trace_add("write", _on_server_username_changed)

    notebook.add(trainer_tab, text="trainer")
    notebook.add(pet_tab, text="pet")
    notebook.add(session_tab, text="session")
    notebook.add(stats_tab, text="stats")

    notebook.grid(row=0, column=0, sticky="nsew")

    connection_status = ConnectionStatusPanel(main_frame)
    connection_status.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 4))

    event_log = EventLogPanel(main_frame)
    event_log.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 4))

    whisper_log = WhisperLogPanel(main_frame)
    whisper_log.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))


def main() -> None:
    root = create_root()
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
