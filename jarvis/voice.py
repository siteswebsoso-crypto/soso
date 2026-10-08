"""Entrée/sortie vocale : micro (SpeechRecognition) et synthèse vocale (pyttsx3)."""

from __future__ import annotations

import queue
import re
import threading


class Voice:
    def __init__(self, language: str = "fr-FR", tts: bool = True):
        self.language = language
        self.enabled = tts
        # Toute la synthèse passe par un seul thread (pyttsx3 n'est pas thread-safe) ;
        # les projets en arrière-plan peuvent donc parler sans conflit.
        self._queue: queue.Queue[tuple[str, threading.Event]] = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        if tts:
            threading.Thread(target=self._speaker, daemon=True, name="jarvis-tts").start()

    def _speaker(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            _pick_voice(engine, self.language)
        except Exception as exc:  # noqa: BLE001
            print(f"(synthèse vocale indisponible : {exc})")
            engine = None
        while True:
            text, done = self._queue.get()
            self._idle.clear()
            try:
                if engine:
                    engine.say(text)
                    engine.runAndWait()
            finally:
                done.set()
                if self._queue.empty():
                    self._idle.set()

    def say(self, text: str, wait: bool = True) -> None:
        if not self.enabled:
            return
        clean = re.sub(r"[`*_#>|]|https?://\S+", "", text).strip()
        if not clean:
            return
        done = threading.Event()
        self._idle.clear()
        self._queue.put((clean, done))
        if wait:
            done.wait()

    def listen(self, timeout: float | None = None, phrase_limit: float = 30) -> str | None:
        """Écoute une phrase au micro et renvoie sa transcription (None si rien compris)."""
        import speech_recognition as sr

        self._idle.wait()  # ne pas s'écouter parler
        recognizer = sr.Recognizer()
        recognizer.pause_threshold = 1.0
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            try:
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            except sr.WaitTimeoutError:
                return None
        try:
            return recognizer.recognize_google(audio, language=self.language)
        except (sr.UnknownValueError, sr.RequestError):
            return None


def _pick_voice(engine, language: str) -> None:
    prefix = language.split("-")[0].lower()
    for v in engine.getProperty("voices"):
        langs = " ".join(str(l) for l in (getattr(v, "languages", None) or []))
        if prefix in (v.id + v.name + langs).lower():
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", 185)


def strip_wake_word(transcript: str, wake_word: str) -> str | None:
    """Renvoie la commande si la phrase contient le mot d'éveil, sinon None.

    « Jarvis, allume Spotify » -> « allume Spotify » ; « Jarvis » seul -> « ».
    """
    match = re.search(rf"\b{re.escape(wake_word)}\b[\s,.!?:]*", transcript, re.IGNORECASE)
    if not match:
        return None
    return transcript[match.end():].strip()


STOP_PHRASES = ("merci jarvis", "c'est tout", "ce sera tout", "rien", "stop", "laisse tomber")


def is_dismissal(text: str) -> bool:
    t = text.strip().lower().rstrip(".!")
    return any(t == p or t.startswith(p) for p in STOP_PHRASES)
