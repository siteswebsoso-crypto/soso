"""Audio : micro (détection automatique de fin de phrase), Whisper local, voix macOS."""

from __future__ import annotations

import platform
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Callable

SAMPLE_RATE = 16_000

# Phrases que Whisper « invente » parfois sur du silence
HALLUCINATIONS = ("sous-titres réalisés", "sous-titrage", "amara.org", "merci d'avoir regardé",
                  "abonnez-vous", "♪")


# ====================================================================== voix

def french_voices() -> list[str]:
    if platform.system() != "Darwin":
        return []
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    voices = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s{2,}(fr_\w+)\s", line)
        if m:
            voices.append(m.group(1).strip())
    return voices


def best_voice(preferred: str = "") -> str:
    voices = french_voices()
    if preferred and preferred in voices:
        return preferred
    for marker in ("Premium", "Enhanced", "Amélioré"):
        for v in voices:
            if marker in v:
                return v
    for name in ("Audrey", "Amélie", "Thomas", "Aurélie"):
        for v in voices:
            if v.startswith(name):
                return v
    return voices[0] if voices else ""


class Speaker:
    """File de phrases lues l'une après l'autre ; interruptible à tout moment."""

    def __init__(self, voice: str = "", rate: int = 180, on_sentence: Callable[[str], None] | None = None):
        self.voice = best_voice(voice)
        self.rate = rate
        self.on_sentence = on_sentence
        self._queue: queue.Queue[str] = queue.Queue()
        self._proc: subprocess.Popen | None = None
        self._idle = threading.Event()
        self._idle.set()
        self._generation = 0
        threading.Thread(target=self._loop, daemon=True, name="speaker").start()

    def say(self, text: str) -> None:
        text = re.sub(r"[*_#`|>]", "", text).strip()
        if text:
            self._idle.clear()
            self._queue.put(text)

    def stop(self) -> None:
        self._generation += 1
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
        self._idle.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    @property
    def speaking(self) -> bool:
        return not self._idle.is_set()

    def _command(self, text: str) -> list[str] | None:
        if platform.system() == "Darwin":
            cmd = ["say", "-r", str(self.rate)]
            if self.voice:
                cmd += ["-v", self.voice]
            return cmd + [text]
        for exe in ("espeak-ng", "espeak"):
            if shutil.which(exe):
                return [exe, "-v", "fr", text]
        return None

    def _loop(self) -> None:
        while True:
            text = self._queue.get()
            generation = self._generation
            if self.on_sentence:
                self.on_sentence(text)
            cmd = self._command(text)
            if cmd:
                self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._proc.wait()
            else:
                time.sleep(min(4, 0.06 * len(text)))  # pas de synthèse : simple délai de lecture
            if self._queue.empty() and generation == self._generation:
                self._idle.set()


# ====================================================================== micro

class Recorder:
    """Enregistre une phrase : démarre quand l'enfant parle, s'arrête après un silence."""

    def __init__(self, on_level: Callable[[float], None] | None = None):
        self.on_level = on_level
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def record(self, wait_speech: float = 12, silence: float = 1.4, max_seconds: float = 60):
        """Renvoie un tableau numpy float32 (16 kHz), ou None si l'enfant n'a rien dit."""
        import numpy as np
        import sounddevice as sd

        self._stop.clear()
        chunks: queue.Queue = queue.Queue()
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=1600,
                            callback=lambda data, *_: chunks.put(data.copy())):
            frames, noise, speaking = [], [], False
            started, last_voice = time.time(), None
            while not self._stop.is_set():
                try:
                    data = chunks.get(timeout=0.5)
                except queue.Empty:
                    continue
                rms = float(np.sqrt(np.mean(data ** 2)))
                if self.on_level:
                    self.on_level(min(1.0, rms * 12))
                now = time.time()
                if len(noise) < 3:  # 0,3 s pour mesurer le bruit ambiant
                    noise.append(rms)
                    continue
                threshold = max(0.012, 3 * float(np.median(noise)))
                if rms > threshold:
                    speaking, last_voice = True, now
                if speaking:
                    frames.append(data)
                    if now - last_voice > silence or now - started > max_seconds:
                        break
                elif now - started > wait_speech:
                    return None
                else:
                    frames = (frames + [data])[-3:]  # garde le tout début du mot
        if not speaking or len(frames) < 4:
            return None
        return np.concatenate(frames)[:, 0]


# ====================================================================== transcription

class Transcriber:
    def __init__(self, model: str):
        self.model = model
        self._backend = None
        self._lock = threading.Lock()

    def warm_up(self) -> None:
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        with self._lock:
            if self._backend is None:
                try:
                    import mlx_whisper  # puce Apple
                    self._backend = ("mlx", mlx_whisper)
                except ImportError:
                    from faster_whisper import WhisperModel
                    self._backend = ("faster", WhisperModel("small", compute_type="int8"))
            return self._backend

    def transcribe(self, audio, hint: str = "") -> str:
        kind, engine = self._load()
        if kind == "mlx":
            text = engine.transcribe(audio, path_or_hf_repo=self.model, language="fr",
                                     initial_prompt=hint or None, condition_on_previous_text=False)["text"]
        else:
            segments, _ = engine.transcribe(audio, language="fr", initial_prompt=hint or None)
            text = " ".join(s.text for s in segments)
        text = text.strip()
        if any(h in text.lower() for h in HALLUCINATIONS):
            return ""
        return text
