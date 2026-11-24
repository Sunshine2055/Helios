"""
Local wake-word detection for HELIOS ("Hello").

Design goals:
  • ZERO cost when the feature is off — Vosk is imported ONLY inside
    start()/install helpers, never at module load. If the user never enables
    wake word, none of this touches the app.
  • ZERO latency on the audio path — the microphone callback only ever does a
    cheap, non-blocking queue push (feed()); the actual model inference runs in
    this module's own background thread, so the real-time audio thread and the
    Gemini stream are never slowed.
  • Fully local & offline — audio fed here never leaves the machine; there is no
    network call except the one-time model download the user triggers from the UI.

Vosk runs fully offline once its small English model has been downloaded. Its
recognizer is constrained to "hello", so sleeping audio never leaves the device.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

# Vosk's lightweight English model; the recognizer grammar only accepts Hello.
WAKE_MODEL = "vosk-model-small-en-us-0.15"
WAKE_MODEL_URL = f"https://alphacephei.com/vosk/models/{WAKE_MODEL}.zip"
SAMPLE_RATE = 16000
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
MAX_MODEL_BYTES = 250 * 1024 * 1024


def _model_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return root / "Helios-Core" / "models" / WAKE_MODEL


def _is_wake_phrase(text: str) -> bool:
    return " ".join(re.findall(r"[a-z]+", str(text or "").casefold())) == "hello"


def is_installed() -> bool:
    """True if Vosk is importable (no model check)."""
    try:
        import importlib.util
        return importlib.util.find_spec("vosk") is not None
    except Exception:
        return False


def is_ready() -> bool:
    """True if Vosk is installed and the local wake model is present."""
    try:
        import importlib.util
        return bool(
            importlib.util.find_spec("vosk") is not None
            and (_model_dir() / "am" / "final.mdl").is_file()
            and (_model_dir() / "conf" / "model.conf").is_file()
        )
    except Exception:
        return False


def install_and_download(logger: Callable[[str], None] = print,
                         notify: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """
    One-click setup for the UI button: install Vosk if missing, then download
    its model into the per-user cache. Returns (ok, message); failures are
    reported to the logger and the caller.
    """
    _tell = notify or (lambda _msg: None)
    try:
        if not is_installed():
            logger("Wake word: installing Vosk (one-time)…")
            _tell("Wake word: installing Vosk (one-time)…")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "vosk"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if r.returncode != 0:
                tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
                return False, f"pip install failed: {tail[0][:160]}"
        if is_ready():
            return True, "Hello wake word is installed and ready."

        model_parent = _model_dir().parent
        model_parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="hello-wake-", dir=model_parent))
        try:
            archive_path = temp_dir / "model.zip"
            logger("Wake word: downloading the local Hello model…")
            _tell("Wake word: downloading the local Hello model…")
            request = urllib.request.Request(
                WAKE_MODEL_URL,
                headers={"User-Agent": "Helios-Core/1.0"},
            )
            total = 0
            with urllib.request.urlopen(request, timeout=90) as response:
                with archive_path.open("wb") as archive_file:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            return False, "model download exceeded the 100 MB safety limit."
                        archive_file.write(chunk)

            extract_dir = temp_dir / "extracted"
            extract_dir.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                if sum(member.file_size for member in members) > MAX_MODEL_BYTES:
                    return False, "model archive exceeded the 250 MB safety limit."
                for member in members:
                    target = (extract_dir / member.filename).resolve()
                    if extract_dir.resolve() not in target.parents:
                        return False, "model archive contains an unsafe path."
                archive.extractall(extract_dir)

            model_candidates = [
                path for path in extract_dir.iterdir()
                if path.is_dir() and (path / "am" / "final.mdl").is_file()
            ]
            if len(model_candidates) != 1:
                return False, "downloaded archive did not contain the expected Vosk model."
            destination = _model_dir()
            if destination.exists():
                return False, f"an incomplete model already exists at {destination}."
            model_candidates[0].rename(destination)
        finally:
            try:
                shutil.rmtree(temp_dir)
            except OSError as exc:
                logger(f"Wake word: temporary download cleanup failed: {exc}")

        if not is_ready():
            return False, "installed, but the Hello wake model is incomplete."
        logger("Wake word: Hello is ready.")
        return True, "Hello wake word installed and ready."
    except Exception as e:
        return False, f"setup error: {e}"


class WakeWordDetector:
    """
    Runs the wake model in a dedicated thread. The mic thread calls feed() with
    raw int16 frames; detections invoke on_detect() (called from this thread —
    the callback must marshal to whatever loop/UI it needs).
    """

    def __init__(self, on_detect: Callable[[], None],
                 logger: Callable[[str], None] = print,
                 notify: Callable[[str], None] | None = None):
        self._on_detect = on_detect
        self._logger    = logger
        # See PluginRegistry: `logger` is the console and gets everything,
        # `notify` is the activity log and gets only what the user must act on.
        self._notify    = notify or (lambda _msg: None)
        self._queue: queue.Queue = queue.Queue(maxsize=50)
        self._thread: threading.Thread | None = None
        self._running = False
        self._model = None
        self._recognizer = None
        self._ready = False

    def start(self) -> bool:
        """Load the model and spawn the inference thread. Returns True on success.
        Safe to call again — a no-op if already running. Never raises."""
        if self._running:
            return True
        try:
            from vosk import KaldiRecognizer, Model
            if not is_ready():
                raise FileNotFoundError("the local Hello model is not installed")
            self._model = Model(str(_model_dir()))
            self._recognizer = KaldiRecognizer(
                self._model,
                SAMPLE_RATE,
                json.dumps(["hello", "[unk]"]),
            )
        except Exception as e:
            self._logger(f"Wake word: could not load model — {e}")
            self._notify("Hello wake word unavailable — use the WAKE NOW button.")
            self._model = None
            self._recognizer = None
            return False
        self._running = True
        self._ready = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="WakeWordThread")
        self._thread.start()
        self._logger("Wake word: listening for 'Hello'.")
        return True

    def stop(self) -> None:
        self._running = False
        # unblock the thread if it's waiting on the queue
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        self._model = None
        self._recognizer = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def feed(self, frame_int16) -> None:
        """Called from the mic callback (real-time thread). Must stay cheap and
        never block — the frame is copied and dropped if the queue is backed up."""
        if not self._running:
            return
        try:
            # frame_int16 is a numpy int16 array (possibly 2-D mono) — flatten to 1-D
            data = frame_int16[:, 0].copy() if getattr(frame_int16, "ndim", 1) > 1 else frame_int16.copy()
            self._queue.put_nowait(data)
        except queue.Full:
            pass
        except Exception:
            pass

    def _loop(self) -> None:
        import numpy as np
        while self._running:
            try:
                frame = self._queue.get()
                if frame is None or not self._running:
                    break
                audio = np.asarray(frame, dtype=np.int16).reshape(-1).tobytes()
                if not self._recognizer.AcceptWaveform(audio):
                    continue
                text = json.loads(self._recognizer.Result()).get("text", "")
                if _is_wake_phrase(text):
                    self._drain()
                    self._recognizer.Reset()
                    try:
                        self._on_detect()
                    except Exception as e:
                        self._logger(f"Wake word: on_detect error — {e}")
            except Exception as e:
                self._logger(f"Wake word: inference error — {e}")

    def _drain(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except Exception:
            pass
