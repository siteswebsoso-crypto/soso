"""Entrée/sortie vocale : micro (SpeechRecognition) et synthèse vocale (pyttsx3)."""

from __future__ import annotations

import re
import threading


class Voice:
    def __init__(self, language: str = "fr-FR", tts: bool = True):
        self.language = language
        self._tts_lock = threading.Lock()
        self._engine = None
        if tts:
            try:
                import pyttsx3
                self._engine = pyttsx3.init()
                self._pick_voice()
            except Exception as exc:  # noqa: BLE001
                print(f"(synthèse vocale indisponible : {exc})")

    def _pick_voice(self) -> None:
        prefix = self.language.split("-")[0].lower()
        for v in self._engine.getProperty("voices"):
            langs = " ".join(str(l) for l in (getattr(v, "languages", None) or []))
            if prefix in (v.id + v.name + langs).lower():
                self._engine.setProperty("voice", v.id)
                break
        self._engine.setProperty("rate", 185)

    def say(self, text: str) -> None:
        if not self._engine:
            return
        clean = re.sub(r"[`*_#>]|https?://\S+", "", text)
        with self._tts_lock:
            self._engine.say(clean)
            self._engine.runAndWait()

    def listen(self, timeout: float | None = None, phrase_limit: float = 20) -> str | None:
        """Écoute une phrase au micro et renvoie sa transcription (None si rien compris)."""
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        recognizer.pause_threshold = 0.8
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


def strip_wake_word(transcript: str, wake_word: str) -> str | None:
    """Renvoie la commande si la phrase contient le mot d'éveil, sinon None.

    « Jarvis, allume Spotify » -> « allume Spotify » ; « Jarvis » seul -> « ».
    """
    match = re.search(rf"\b{re.escape(wake_word)}\b[\s,.!?:]*", transcript, re.IGNORECASE)
    if not match:
        return None
    return transcript[match.end():].strip()
