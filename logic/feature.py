from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type

from logic.logging_utils import SessionLogManager


@dataclass
class FeatureContext:
    """Shared interfaces/config passed to feature constructors."""

    role: str
    osc: Any = None
    pishock: Any = None
    whisper: Any = None
    server: Any = None
    log_manager: SessionLogManager | None = None
    settings: Dict[str, Any] | None = None
    config_provider: Callable[[], Dict[str, dict]] | None = None


class Feature:
    """Base feature with common interface wiring and logging."""

    log_name: Optional[str] = None
    ui_label: Optional[str] = None
    role: str = "shared"
    feature_name: str = ""

    def __init__(
        self,
        *,
        osc: Any = None,
        pishock: Any = None,
        whisper: Any = None,
        server: Any = None,
        logger: Any = None,
        log_manager: SessionLogManager | None = None,
        log_name: str | None = None,
        config_provider: Callable[[], Dict[str, dict]] | None = None,
        settings: Dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        self.osc = osc
        self.pishock = pishock
        self.whisper = whisper
        self.server = server
        self.settings = settings or {}
        self.config_provider = config_provider

        resolved_log_name = log_name or self.log_name
        if logger is not None:
            self._logger = logger
        elif log_manager is not None and resolved_log_name:
            try:
                self._logger = log_manager.get_logger(resolved_log_name)
            except Exception:
                self._logger = None
        else:
            self._logger = None

        self._running: bool = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._poll_interval: float = 0.5
        self._cooldown_until: float = 0.0
        self._base_cooldown_seconds: float = 2
        self._base_timeout_seconds: float = 4.0
        self._base_shock_duration: float = 0.2
        self._base_shock_strength: float = 50
        self._base_shock_strength_min: float = 10
        self._base_shock_strength_max: float = 50

        self._log("init")


    @staticmethod
    def normalise_text(text: str) -> str:
        if not text:
            return ""

        chars: list[str] = []
        for ch in text.lower():
            if ch.isalnum():
                chars.append(ch)
            elif ch.isspace():
                chars.append(" ")
            else:
                chars.append(" ")

        return " ".join("".join(chars).split())

    @staticmethod
    def normalise_list(words: list[str] | None) -> list[str]:
        return [Feature.normalise_text(word) for word in (words or []) if Feature.normalise_text(word)]

    # Lifecycle helpers -------------------------------------------------
    def _start_worker(self, *, target: Callable[[], None], name: str) -> None:
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self.whisper.reset_tag(self.feature_name)

        thread = threading.Thread(target=target, name=name, daemon=True)
        self._thread = thread
        thread.start()

        self._log("start")

    def _stop_worker(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None

        self._log("stop")

    # Logging -----------------------------------------------------------
    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is None:
            return

        try:
            logger.log(message)
        except Exception:
            return

    # Config helpers ----------------------------------------------------
    def _config_map(self) -> Dict[str, dict]:
        provider = self.config_provider
        if provider is None:
            return {}

        try:
            configs = provider() or {}
        except Exception:
            return {}

        if not isinstance(configs, dict):
            return {}
        return {cid: cfg for cid, cfg in configs.items() if isinstance(cfg, dict)}

    def _extract_word_list(self, config: dict, key: str) -> list[str]:
        values = config.get(key) if isinstance(config, dict) else None
        return self.normalise_list(values)

    def _latest_trainer_settings(self) -> Dict[str, dict]:
        configs = self._config_map()
        if configs:
            return configs

        server = self.server
        if server is None:
            return {}

        raw_configs = getattr(server, "latest_settings_by_trainer", None)
        configs = raw_configs() if callable(raw_configs) else raw_configs
        if not isinstance(configs, dict):
            return {}
        return configs

    # Scaling helpers ---------------------------------------------------
    @staticmethod
    def _scaling_from_config(config: dict) -> dict[str, float]:
        def _safe(key: str) -> float:
            try:
                val = float(config.get(key, 1.0))
            except Exception:
                val = 1.0
            return max(0.0, min(2.0, val))

        return {
            "delay_scale": _safe("delay_scale"),
            "cooldown_scale": _safe("cooldown_scale"),
            "duration_scale": _safe("duration_scale"),
            "strength_scale": _safe("strength_scale"),
        }

    def _scaled_value(self, base: float, config: dict, scale_key: str) -> float:
        scaling = self._scaling_from_config(config)
        return max(0.0, base * scaling.get(scale_key, 1.0))

    def _scaled_cooldown(self, config: dict) -> float:
        base = self._base_cooldown_seconds
        return self._scaled_value(base, config, "cooldown_scale")

    def _scaled_timeout(self, config: dict) -> float:
        base = self._base_timeout_seconds
        return self._scaled_value(base, config, "delay_scale")

    def _scaled_duration(self, config: dict) -> float:
        base = self._base_shock_duration
        return self._scaled_value(base, config, "duration_scale")

    def _scaled_strength_single(self, config: dict) -> float:
        base = self._base_shock_strength
        return self._scaled_value(base, config, "strength_scale")

    def _scaled_strength_range(self, config: dict) -> tuple[float, float]:
        scaling = self._scaling_from_config(config)
        base_min = self._base_shock_strength_min
        base_max = self._base_shock_strength_max
        shock_min = max(0.0, base_min * scaling["strength_scale"])
        shock_max = max(shock_min, base_max * scaling["strength_scale"])
        return shock_min, shock_max

    def _shock_params_single(self, config: dict) -> tuple[float, float]:
        strength = self._scaled_strength_single(config)
        duration = self._scaled_duration(config)
        return strength, duration

    def _shock_params_range(self, config: dict) -> tuple[float, float, float]:
        shock_min, shock_max = self._scaled_strength_range(config)
        shock_duration = self._scaled_duration(config)
        return shock_min, shock_max, shock_duration

    def _send_logs(self, stats: dict[str, object], *, target_clients: str | None = None, broadcast_trainers: bool | None = None) -> None:
        stats["role"] = self.role
        stats["feature"] = self.feature_name
        self.server.send_logs(stats, target_clients, broadcast_trainers)


class TrainerFeature(Feature):
    """Base class for trainer-side features."""

    role = "trainer"

    def _iter_pet_configs(self) -> Dict[str, dict]:
        return self._config_map()

    def _pulse_command_flag(self, flag_name: str) -> None:
        osc = self.osc
        if osc is None:
            return

        try:
            osc.pulse_parameter(flag_name, value_on=1, value_off=0, duration=0.2)
        except Exception:
            return

    def _has_active_pet(self) -> bool:
        configs = self._latest_trainer_settings()
        flag = self.feature_name
        if not flag:
            return configs
        return any(tid for tid, cfg in configs.items() if cfg.get(flag))


class PetFeature(Feature):
    """Base class for pet-side features."""

    role = "pet"

    def _active_trainer_configs(self) -> Dict[str, dict]:
        configs = self._latest_trainer_settings()
        flag = self.feature_name
        if not flag:
            return configs
        return {tid: cfg for tid, cfg in configs.items() if cfg.get(flag)}

    def _has_active_trainer(self) -> bool:
        return bool(self._active_trainer_configs())


FeatureKwargsBuilder = Callable[[str, FeatureContext], Dict[str, Any]]


@dataclass
class FeatureDefinition:
    """Declarative description of a feature and its runtime wiring."""

    key: str
    label: str
    trainer_cls: Type[TrainerFeature] | None = None
    pet_cls: Type[PetFeature] | None = None
    trainer_log: str | None = None
    pet_log: str | None = None
    enabled_by_default: bool = False
    show_in_ui: bool = True
    ui_column: int = 0
    build_kwargs: FeatureKwargsBuilder | None = None

    def resolve_class(self, role: str) -> Type[Feature] | None:
        if role == "trainer":
            return self.trainer_cls
        if role == "pet":
            return self.pet_cls
        return None

    def resolve_log_name(self, role: str) -> str | None:
        if role == "trainer":
            return self.trainer_log
        if role == "pet":
            return self.pet_log
        return None

    def kwargs_for(self, role: str, context: FeatureContext) -> Dict[str, Any]:
        if self.build_kwargs is None:
            return {}

        try:
            return self.build_kwargs(role, context) or {}
        except Exception:
            return {}

    def build_feature(self, role: str, context: FeatureContext) -> Feature | None:
        cls = self.resolve_class(role)
        if cls is None:
            return None

        kwargs = self.kwargs_for(role, context)
        return cls(
            osc=context.osc,
            pishock=context.pishock,
            whisper=context.whisper,
            server=context.server,
            log_manager=context.log_manager,
            log_name=self.resolve_log_name(role),
            config_provider=context.config_provider,
            settings=context.settings,
            **kwargs,
        )


def _trainer_names_kwargs(role: str, context: FeatureContext) -> Dict[str, Any]:
    if role != "trainer":
        return {}
    settings = context.settings or {}
    return {"names": settings.get("names") or [], "config_provider": context.config_provider}


def _trainer_scolding_kwargs(role: str, context: FeatureContext) -> Dict[str, Any]:
    if role != "trainer":
        return {}
    settings = context.settings or {}
    return {"scolding_words": settings.get("scolding_words") or [], "config_provider": context.config_provider}


def feature_definitions() -> List[FeatureDefinition]:
    """Return all feature definitions for both trainer and pet roles."""
    from logic.pet.depth import DepthFeature
    from logic.pet.focus import FocusFeature
    from logic.pet.forbidden import ForbiddenWordsFeature
    from logic.pet.proximity import ProximityFeature
    from logic.pet.pull import PullFeature
    from logic.pet.scolding import ScoldingFeature
    from logic.pet.tricks import TricksFeature
    from logic.pet.wordgame import WordFeature
    from logic.trainer.focus import TrainerFocusFeature
    from logic.trainer.proximity import TrainerProximityFeature
    from logic.trainer.scolding import TrainerScoldingFeature
    from logic.trainer.tricks import TrainerTricksFeature

    return [
        FeatureDefinition(
            key="feature_focus",
            label="Focus",
            trainer_cls=TrainerFocusFeature,
            pet_cls=FocusFeature,
            trainer_log="trainer_focus_feature.log",
            pet_log="focus_feature.log",
            build_kwargs=_trainer_names_kwargs,
        ),
        FeatureDefinition(
            key="feature_proximity",
            label="Proximity",
            trainer_cls=TrainerProximityFeature,
            pet_cls=ProximityFeature,
            trainer_log="trainer_proximity_feature.log",
            pet_log="proximity_feature.log",
            build_kwargs=_trainer_names_kwargs,
        ),
        FeatureDefinition(
            key="feature_tricks",
            label="Tricks",
            trainer_cls=TrainerTricksFeature,
            pet_cls=TricksFeature,
            trainer_log="trainer_tricks_feature.log",
            pet_log="tricks_feature.log",
            build_kwargs=_trainer_names_kwargs,
        ),
        FeatureDefinition(
            key="feature_scolding",
            label="Scolding words",
            trainer_cls=TrainerScoldingFeature,
            pet_cls=ScoldingFeature,
            trainer_log="trainer_scolding_feature.log",
            pet_log="scolding_feature.log",
            build_kwargs=_trainer_scolding_kwargs,
        ),
        FeatureDefinition(
            key="feature_forbidden_words",
            label="Forbidden words",
            pet_cls=ForbiddenWordsFeature,
            pet_log="forbidden_words_feature.log",
        ),
        FeatureDefinition(
            key="feature_ear_tail",
            label="Ear/Tail pull",
            pet_cls=PullFeature,
            pet_log="pull_feature.log",
            ui_column=1,
        ),
        FeatureDefinition(
            key="feature_depth",
            label="Depth",
            pet_cls=DepthFeature,
            pet_log="depth_feature.log",
            ui_column=1,
        ),
        FeatureDefinition(
            key="feature_pronouns",
            label="Pronouns",
            pet_cls=WordFeature,
            pet_log="wordgame_feature.log",
            show_in_ui=False,
        ),
    ]


def feature_defaults() -> Dict[str, bool]:
    """Return default enablement flags keyed by feature config key."""
    return {definition.key: definition.enabled_by_default for definition in feature_definitions()}


def ui_feature_definitions() -> List[FeatureDefinition]:
    """Return feature definitions intended for UI toggle construction."""
    return [definition for definition in feature_definitions() if definition.show_in_ui]


def build_features_for_role(role: str, context: FeatureContext) -> List[Feature]:
    """Instantiate all features matching a given role."""
    instances: List[Feature] = []
    for definition in feature_definitions():
        feature = definition.build_feature(role, context)
        if feature is not None:
            instances.append(feature)
    return instances
