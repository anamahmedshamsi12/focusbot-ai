"""
voice.py
--------
Text-to-speech engine for FocusBot.
Handles initialization and speaking in a background thread
so the UI never freezes while waiting for speech to finish.
"""

import re
import threading
import pyttsx3

from focusbot.config import VOICE_ENABLED


def init_tts() -> pyttsx3.Engine | None:
    """
    Initialize and configure the pyttsx3 TTS engine.

    Sets speaking rate, volume, and attempts to select a
    slightly higher-pitched voice for a robot-like feel.

    Returns:
        Configured pyttsx3 engine, or None if initialization fails.
    """
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 160)    # words per minute
        engine.setProperty("volume", 0.9)  # 0.0 – 1.0

        # Use the second available voice if one exists (often higher-pitched)
        voices = engine.getProperty("voices")
        if len(voices) > 1:
            engine.setProperty("voice", voices[1].id)

        return engine

    except Exception as exc:
        print(f"[FocusBot] TTS init failed: {exc}")
        return None


def speak(text: str, engine: pyttsx3.Engine | None) -> None:
    """
    Speak text aloud in a daemon background thread.

    Strips non-ASCII characters (e.g. emojis) before speaking
    so the TTS engine doesn't stumble on them.

    Args:
        text:   The string to speak.
        engine: An initialized pyttsx3 engine, or None to skip speech.
    """
    if not VOICE_ENABLED or engine is None:
        return

    # Remove emojis and other non-ASCII characters
    clean_text = re.sub(r"[^\x00-\x7F]+", "", text)

    def _run() -> None:
        try:
            engine.say(clean_text)
            engine.runAndWait()
        except Exception:
            pass  # Speech is non-critical — silently ignore errors

    threading.Thread(target=_run, daemon=True).start()
