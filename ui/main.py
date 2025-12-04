import tkinter as tk
from tkinter import ttk, font

from config import load_config, save_config
from interfaces.audio_devices import list_input_devices
from logic import services
from logic.trainer import profile as trainer_profile

from .settings import SettingsTab
from .trainer import TrainerTab
from .pet import PetTab
from .stats import StatsTab


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

    notebook = ttk.Notebook(root)

    # Settings tab -------------------------------------------------------
    def on_settings_changed(settings: dict) -> None:
        section = config.setdefault("settings", {})
        section["input_device"] = settings.get("input_device")
        save_config(config)

    settings_tab = SettingsTab(notebook, on_settings_change=on_settings_changed)

    # Populate available input devices.
    devices = list_input_devices()
    settings_tab.set_input_devices(devices)

    # Restore settings from config, preferring a stored device if present.
    settings_conf = config.get("settings") or {}
    stored_device = settings_conf.get("input_device")
    if stored_device:
        # If the stored device is not in the current list (e.g. unplugged),
        # still show it so the user can see what was last used.
        if stored_device not in devices:
            settings_tab.set_input_devices(devices + [stored_device])
        settings_tab.input_device_row.variable.set(stored_device)

    # Trainer tab --------------------------------------------------------
    def on_trainer_settings_changed(settings: dict) -> None:
        trainer_profile.update_profile_from_settings(config, settings)
        save_config(config)
        if services.is_trainer_running():
            services.update_trainer_feature_states(settings)
        # Mirror trainer-controlled pet feature toggles into the pet tab and running pet runtime.
        pet_tab.set_feature_flags(
            feature_focus=settings.get("feature_focus", False),
            feature_proximity=settings.get("feature_proximity", False),
            feature_tricks=settings.get("feature_tricks", False),
            feature_scolding=settings.get("feature_scolding", False),
            feature_ear_tail=settings.get("feature_ear_tail", False),
            feature_pronouns=settings.get("feature_pronouns", False),
        )
        if services.is_pet_running():
            services.update_pet_feature_states(
                {
                    "feature_focus": settings.get("feature_focus"),
                    "feature_proximity": settings.get("feature_proximity"),
                    "feature_tricks": settings.get("feature_tricks"),
                    "feature_scolding": settings.get("feature_scolding"),
                    "feature_ear_tail": settings.get("feature_ear_tail"),
                    "feature_pronouns": settings.get("feature_pronouns"),
                    "delay_scale": settings.get("delay_scale"),
                    "cooldown_scale": settings.get("cooldown_scale"),
                    "duration_scale": settings.get("duration_scale"),
                    "strength_scale": settings.get("strength_scale"),
                    "names": settings.get("names"),
                    "command_words": settings.get("command_words"),
                    "scolding_words": settings.get("scolding_words"),
                }
            )

    def on_trainer_profile_selected(profile_name: str) -> None:
        if not profile_name:
            trainer_profile.set_active_profile_name(config, None)
            save_config(config)
            pet_tab.set_feature_flags(
                feature_focus=False,
                feature_proximity=False,
                feature_tricks=False,
                feature_scolding=False,
                feature_ear_tail=False,
                feature_pronouns=False,
            )
            return

        trainer_profile.set_active_profile_name(config, profile_name)
        current = trainer_profile.get_profile(config, profile_name)
        if current is None:
            current = trainer_profile.default_profile_settings(profile_name)
            trainer_profile.update_profile_from_settings(config, current)
        trainer_tab.apply_profile_settings(current)
        pet_tab.set_feature_flags(
            feature_focus=current.get("feature_focus", False),
            feature_proximity=current.get("feature_proximity", False),
            feature_tricks=current.get("feature_tricks", False),
            feature_scolding=current.get("feature_scolding", False),
            feature_ear_tail=current.get("feature_ear_tail", False),
            feature_pronouns=current.get("feature_pronouns", False),
        )
        save_config(config)

    def on_trainer_profile_renamed(old_name: str, new_name: str) -> None:
        if trainer_profile.rename_profile(config, old_name, new_name):
            save_config(config)

    def on_trainer_profile_deleted(profile_name: str) -> None:
        if trainer_profile.delete_profile(config, profile_name):
            save_config(config)

    def on_trainer_start(running: bool) -> None:
        """Callback for when the Trainer tab Start/Stop button is toggled."""
        if running:
            # When starting, launch all interfaces and enabled features.
            trainer_settings = trainer_tab.collect_settings()
            input_device = settings_tab.input_device
            services.start_trainer(trainer_settings, input_device)
        else:
            # When stopping, tear down all running trainer services.
            services.stop_trainer()

    trainer_tab = TrainerTab(
        notebook,
        on_settings_change=on_trainer_settings_changed,
        on_start=on_trainer_start,
        on_profile_selected=on_trainer_profile_selected,
        on_profile_renamed=on_trainer_profile_renamed,
        on_profile_deleted=on_trainer_profile_deleted,
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

    def on_pet_start(running: bool) -> None:
        """Callback for when the Pet tab Start/Stop button is toggled."""
        if running:
            pet_settings = pet_tab.collect_settings()
            trainer_settings = trainer_tab.collect_settings()
            # Copy trainer-controlled feature toggles and vocab to the pet runtime.
            pet_settings.update(
                {
                    "feature_focus": trainer_settings.get("feature_focus"),
                    "feature_proximity": trainer_settings.get("feature_proximity"),
                    "feature_tricks": trainer_settings.get("feature_tricks"),
                    "feature_scolding": trainer_settings.get("feature_scolding"),
                    "feature_ear_tail": trainer_settings.get("feature_ear_tail"),
                    "feature_pronouns": trainer_settings.get("feature_pronouns"),
                    "delay_scale": trainer_settings.get("delay_scale"),
                    "cooldown_scale": trainer_settings.get("cooldown_scale"),
                    "duration_scale": trainer_settings.get("duration_scale"),
                    "strength_scale": trainer_settings.get("strength_scale"),
                    "names": trainer_settings.get("names"),
                    "command_words": trainer_settings.get("command_words"),
                    "scolding_words": trainer_settings.get("scolding_words"),
                }
            )
            input_device = settings_tab.input_device
            services.start_pet(pet_settings, input_device)
        else:
            services.stop_pet()

    pet_tab = PetTab(notebook, on_settings_change=on_pet_settings_changed, on_start=on_pet_start)

    # Restore pet settings from config, if any.
    pet_settings_conf = config.get("pet") or {}
    if pet_settings_conf:
        pet_tab.apply_settings(pet_settings_conf)
    # Keep pet feature status aligned with the currently active trainer profile.
    current_trainer_settings = trainer_tab.collect_settings()
    pet_tab.set_feature_flags(
        feature_focus=current_trainer_settings.get("feature_focus", False),
        feature_proximity=current_trainer_settings.get("feature_proximity", False),
        feature_tricks=current_trainer_settings.get("feature_tricks", False),
        feature_scolding=current_trainer_settings.get("feature_scolding", False),
        feature_ear_tail=current_trainer_settings.get("feature_ear_tail", False),
        feature_pronouns=current_trainer_settings.get("feature_pronouns", False),
    )

    stats_tab = StatsTab(notebook)

    notebook.add(settings_tab, text="settings")
    notebook.add(trainer_tab, text="trainer")
    notebook.add(pet_tab, text="pet")
    notebook.add(stats_tab, text="stats")

    notebook.pack(fill="both", expand=True)

    def _refresh_osc_status() -> None:
        # OSC diagnostics
        trainer_status = services.get_trainer_osc_status()
        if trainer_status is not None:
            trainer_tab.update_osc_status(trainer_status)

        pet_status = services.get_pet_osc_status()
        if pet_status is not None:
            pet_tab.update_osc_status(pet_status)

        # PiShock status
        trainer_pishock = services.get_trainer_pishock_status()
        if trainer_pishock is not None:
            if not trainer_pishock.get("enabled", True):
                trainer_tab.pishock_status.set_status("Disabled (pet-side only)", "grey")
            elif trainer_pishock["connected"]:
                trainer_tab.pishock_status.set_status("Connected", "green")
            elif trainer_pishock["has_credentials"]:
                trainer_tab.pishock_status.set_status("Not connected", "red")
            else:
                trainer_tab.pishock_status.set_status("Not configured", "orange")

        pet_pishock = services.get_pet_pishock_status()
        if pet_pishock is not None:
            if not pet_pishock.get("enabled", True):
                pet_tab.pishock_status.set_status("Disabled (pet-side only)", "grey")
            elif pet_pishock["connected"]:
                pet_tab.pishock_status.set_status("Connected", "green")
            elif pet_pishock["has_credentials"]:
                pet_tab.pishock_status.set_status("Not connected", "red")
            else:
                pet_tab.pishock_status.set_status("Not configured", "orange")

        # Whisper transcript log
        trainer_whisper_text = services.get_trainer_whisper_log_text()
        if trainer_whisper_text:
            trainer_tab.append_whisper_log(trainer_whisper_text)

        pet_whisper_text = services.get_pet_whisper_log_text()
        if pet_whisper_text:
            pet_tab.whisper_log.configure(state="normal")
            pet_tab.whisper_log.insert("end", pet_whisper_text + "\n")
            pet_tab.whisper_log.see("end")
            pet_tab.whisper_log.configure(state="disabled")

        root.after(1000, _refresh_osc_status)

    _refresh_osc_status()


def main() -> None:
    root = create_root()
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
