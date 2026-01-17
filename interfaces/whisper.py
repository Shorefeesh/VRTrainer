from __future__ import annotations

import os
import queue
import threading
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

import logging

_SHARED_WHISPER_MODEL: Any = None
_SHARED_WHISPER_BACKEND: Optional[str] = None
_SHARED_WHISPER_MODEL_LOCK = threading.Lock()


@dataclass
class _TranscriptChunk:
    """Represents a single chunk of recognised text."""

    text: str
    timestamp: float = field(default_factory=time.time)


class WhisperInterface:
    """Interface for running a local Whisper speech-to-text engine.

    This implementation runs a background worker that pulls short audio
    segments from the configured input device, passes them through a
    local Whisper model, and collects recognised text. Features can
    retrieve *new* text since their last call by providing a tag.

    Requirements/assumptions:
    - ``sounddevice`` is used for microphone capture.
    - ``faster_whisper`` is used for speech-to-text.
    - If either dependency is missing, the interface degrades to a
      no-op that simply returns empty transcripts.
    """

    def __init__(self, input_device: Optional[str]) -> None:
        self.input_device = input_device
        self._running = False

        # Background worker thread and coordination primitives.
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Queue of raw audio blocks captured from the microphone.
        # Use an unbounded queue so we never drop audio when Whisper
        # is temporarily slower than real time; this prevents missing
        # transcript chunks during continuous speech.
        self._audio_queue: "queue.Queue[bytes]" = queue.Queue()

        # Transcript storage: ordered list of chunks.
        self._transcript: List[_TranscriptChunk] = []

        # Per-tag cursors: index into self._transcript for each feature tag.
        self._tag_positions: Dict[str, int] = {}

        # Lazy-loaded external dependencies; set during start().
        self._whisper_model = None
        self._sd = None  # sounddevice module
        self._backend_label: Optional[str] = None

        # Lock to protect transcript/tag structures.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start transcription for the configured input device.

        If required dependencies are not available, this becomes a
        no-op but the interface remains usable (it just never produces
        any text).
        """
        if self._running:
            return

        # Try importing optional dependencies. Fail soft: if either
        # import fails, mark as running but without background work.
        try:  # pragma: no cover - dependency/environment specific
            import sounddevice as sd  # type: ignore[import-not-found]
        except Exception:  # pragma: no cover - dependency/environment specific
            self._running = True
            return

        # Suppress known deprecation warning emitted by ctranslate2 via
        # faster_whisper about ``pkg_resources`` being deprecated.
        warnings.filterwarnings(
            "ignore",
            message="pkg_resources is deprecated as an API.*",
            category=UserWarning,
            module="ctranslate2",
        )

        try:  # pragma: no cover - dependency/environment specific
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]
        except Exception:  # pragma: no cover - dependency/environment specific
            self._running = True
            self._sd = sd
            return

        self._sd = sd

        # Load a small/fast default model once per process and reuse it.
        global _SHARED_WHISPER_MODEL
        global _SHARED_WHISPER_BACKEND
        with _SHARED_WHISPER_MODEL_LOCK:
            if _SHARED_WHISPER_MODEL is None:
                cache_dir = self._resolve_whisper_cache_dir()
                kwargs: Dict[str, Any] = {}
                if cache_dir is not None:
                    # Ensure model cache is stored in a stable, project-local directory
                    # so we do not redownload on every run.
                    kwargs["download_root"] = str(cache_dir)

                # Let users override the device/compute type via environment
                # variables, but default to CPU to avoid CUDA/cuDNN issues on
                # machines without a full GPU toolchain installed.
                device = os.environ.get("WHISPER_DEVICE", "cuda")
                compute_type = os.environ.get("WHISPER_COMPUTE_TYPE")
                if device:
                    kwargs["device"] = device
                if compute_type:
                    kwargs["compute_type"] = compute_type

                backend_label = self._format_backend_label(device, compute_type)

                _SHARED_WHISPER_MODEL = WhisperModel("small", **kwargs)
                _SHARED_WHISPER_BACKEND = backend_label

            elif _SHARED_WHISPER_BACKEND is None:
                # Model is already loaded but backend label was not set; fall
                # back to an unknown marker instead of lying.
                _SHARED_WHISPER_BACKEND = "Unknown"

        self._whisper_model = _SHARED_WHISPER_MODEL
        self._backend_label = _SHARED_WHISPER_BACKEND

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="WhisperWorker", daemon=True)
        self._thread.start()

        self._running = True

    def stop(self) -> None:
        """Stop transcription."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

        # Best-effort cleanup.
        self._thread = None
        with self._lock:
            # Reset the audio queue; see __init__ for rationale on
            # using an unbounded queue.
            self._audio_queue = queue.Queue()

    @property
    def is_running(self) -> bool:
        return self._running

    def get_backend_summary(self) -> str:
        """Return a human-friendly summary of the active backend.

        Expected values are ``CPU`` or ``GPU (...`` depending on the
        configured device and compute type. Falls back to ``Stopped`` when
        Whisper is not running.
        """

        if not self._running:
            return "Stopped"
        if self._backend_label:
            return self._backend_label
        if self._whisper_model is None:
            return "Unavailable"
        return "Running"

    # ------------------------------------------------------------------
    # Whisper model/cache helpers
    # ------------------------------------------------------------------
    def _resolve_whisper_cache_dir(self) -> Optional[Path]:
        """Return a persistent directory for Whisper model downloads.

        Prefer the ``WHISPER_CACHE_DIR`` env var if set; otherwise fall
        back to a project-local ``models/whisper`` directory.
        """
        base = os.environ.get("WHISPER_CACHE_DIR")
        if base:
            path = Path(base).expanduser()
        else:
            # interfaces/whisper.py -> project_root/interfaces/..
            project_root = Path(__file__).resolve().parent.parent
            path = project_root / "models" / "whisper"

        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None

        return path

    @staticmethod
    def _format_backend_label(device: str | None, compute_type: str | None) -> str:
        device = (device or "cpu").lower()
        base = "CPU" if device == "cpu" else "GPU"
        if compute_type:
            return f"{base} ({compute_type})"
        return base

    # ------------------------------------------------------------------
    # Transcript API
    # ------------------------------------------------------------------
    def get_new_text(self, tag: str) -> str:
        """Return new transcript text for the given tag.

        The first time a tag is seen, its position is initialised to the
        end of the current transcript (i.e. it will only see text
        produced *after* that point). Subsequent calls return all text
        added since the last call for that tag.
        """
        if not tag:
            raise ValueError("tag must be a non-empty string")

        with self._lock:
            # Initialise the cursor if this is a new tag.
            if tag not in self._tag_positions:
                self._tag_positions[tag] = len(self._transcript)

            start_index = self._tag_positions[tag]
            end_index = len(self._transcript)
            if start_index >= end_index:
                return ""

            chunks = self._transcript[start_index:end_index]
            self._tag_positions[tag] = end_index

        return " ".join(chunk.text for chunk in chunks).strip()

    def reset_tag(self, tag: str) -> None:
        """Reset a tag's cursor to the current end of the transcript."""
        if not tag:
            raise ValueError("tag must be a non-empty string")

        with self._lock:
            self._tag_positions[tag] = len(self._transcript)

    def get_recent_text_chunks(self, count: int = 1) -> List[str]:
        """Return up to ``count`` most recent transcript chunks (newest last).

        This does not advance any tag cursors; it is intended for lightweight
        context checks where features need a short look-back window.
        """
        if count <= 0:
            return []

        with self._lock:
            return [chunk.text for chunk in self._transcript[-count:]]

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------
    def _worker_loop(self) -> None:
        """Capture audio and feed it to Whisper in a loop.

        This is intentionally conservative and simple: it records short
        fixed-length buffers, transcribes them synchronously, and
        appends non-empty text to the transcript list.
        """
        if self._sd is None or self._whisper_model is None:
            return

        sd = self._sd
        model = self._whisper_model

        # Basic audio parameters. These can be tuned later if needed.
        samplerate = 16000
        # Shorter windows reduce end-to-end latency and how long the
        # worker spends inside a single transcription call, which in
        # turn limits how much buffered audio builds up.
        block_duration = 3.0  # seconds per transcription window



        # Resolve device: ``None`` lets sounddevice pick the default.
        try:
            if self.input_device:
                # sounddevice can accept device names directly; fall back
                # to default if the name is not recognised.
                all_devices = sd.query_devices()
                selected_devices = [device for device in all_devices if device['name'] == self.input_device]
                if selected_devices:
                    # TODO: Select the first one. Fix later, lol smiley face
                    device_index = selected_devices[0]['index']
                else:
                    device_index = None
        except Exception as e:
            logging.error(e)
            device = None

        try:  # pragma: no cover - environment/hardware specific
            with sd.InputStream(
                samplerate=samplerate,
                channels=1,
                dtype="float32",
                device=device_index,
                blocksize=0,
                callback=self._make_audio_callback(),
            ):
                # Main loop: wake up periodically, batch whatever audio
                # is present, and run a transcription pass.
                while not self._stop_event.is_set():
                    start_time = time.time()
                    frames: List[bytes] = []

                    # Collect audio for roughly block_duration seconds.
                    while time.time() - start_time < block_duration and not self._stop_event.is_set():
                        try:
                            data = self._audio_queue.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        frames.append(data)

                    if not frames or self._stop_event.is_set():
                        continue

                    # Concatenate into a single block for Whisper.
                    import numpy as np  # type: ignore[import-not-found]

                    try:
                        audio = np.concatenate([np.frombuffer(f, dtype="float32") for f in frames])
                    except Exception:
                        continue

                    if audio.size == 0:
                        continue

                    # Simple energy-based noise/silence gate: if the
                    # RMS level of the window is extremely low, skip
                    # transcription entirely. This avoids Whisper
                    # emitting spurious text from background noise.
                    try:
                        rms = float(np.sqrt(np.mean(np.square(audio), dtype="float64")))
                    except Exception:
                        rms = 0.0

                    # This threshold is intentionally conservative; it
                    # can be adjusted via the WHISPER_MIN_RMS
                    # environment variable if needed.
                    min_rms_env = os.environ.get("WHISPER_MIN_RMS")
                    try:
                        min_rms = float(min_rms_env) if min_rms_env is not None else 0.005
                    except ValueError:
                        min_rms = 0.005

                    if rms < min_rms:
                        continue

                    try:
                        # faster_whisper returns an iterator of segments and an
                        # info object. We concatenate the recognised text of all
                        # segments into a single string.
                        # Use the built-in VAD filter when supported to
                        # further reduce noise-only segments.
                        try:
                            segments, _info = model.transcribe(audio, vad_filter=True, language="en")
                        except TypeError:
                            # Older faster_whisper versions may not
                            # support vad_filter; fall back gracefully.
                            segments, _info = model.transcribe(audio, language="en")
                    except Exception:
                        # On any transcription error, skip this block.
                        continue

                    collected_parts: List[str] = []
                    try:
                        for segment in segments:
                            part = getattr(segment, "text", "") or ""
                            part = part.strip()
                            if part:
                                collected_parts.append(part)
                    except Exception:
                        # If iterating over segments fails for any reason, skip.
                        continue

                    text = " ".join(collected_parts).strip()
                    if not text:
                        continue

                    with self._lock:
                        self._transcript.append(_TranscriptChunk(text=text))
        except Exception as e:
            logging.exception("Unexpected exception occurred")
            # If audio capture fails (no device, permission issue, etc.),
            # just exit the worker loop; the interface will stay alive
            # but no text will be produced.
            return

    def _make_audio_callback(self):
        """Create a sounddevice callback that pushes audio into the queue."""

        def _callback(indata, frames, time_info, status):  # pragma: no cover - realtime/audio
            if status:
                # We ignore status warnings/errors here; in a more
                # advanced implementation we might log them to the UI.
                pass

            try:
                # Copy the underlying buffer so it remains valid after
                # the callback returns.
                self._audio_queue.put_nowait(indata.copy().tobytes())
            except queue.Full:
                # Drop audio if we're too far behind.
                pass

        return _callback
