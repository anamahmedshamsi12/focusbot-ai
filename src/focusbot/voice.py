"""
voice.py
--------
Text-to-speech engine for FocusBot.

Primary voice: edge-tts (free, Microsoft neural voices, no API key needed)
Fallback voice: pyttsx3 with Alex (used if edge-tts fails for any reason)

Speaks in a background thread so the UI never freezes.
"""

import asyncio
import os
import re
import tempfile
import threading

import edge_tts
import pyttsx3

from focusbot.config import VOICE_ENABLED

# edge-tts Configuration 
# GuyNeural — clean, natural, male American voice (closest to Siri)
EDGE_VOICE     = "en-GB-RyanNeural"

# Fallback Configuration 
FALLBACK_VOICE = "com.apple.speech.synthesis.voice.Alex"
FALLBACK_RATE  = 185


# pyttsx3 Fallback Engine 
def init_tts() -> pyttsx3.Engine | None:
    """
    Initialize the pyttsx3 fallback TTS engine.
    Used when edge-tts is unavailable (e.g. no internet).

    Returns:
        Configured pyttsx3 engine, or None if initialization fails.
    """
    try:
        engine = pyttsx3.init()
        engine.setProperty("voice",  FALLBACK_VOICE)
        engine.setProperty("rate",   FALLBACK_RATE)
        engine.setProperty("volume", 0.9)
        return engine
    except Exception as exc:
        print(f"[FocusBot] TTS fallback init failed: {exc}")
        return None


# ── edge-tts Speaker ───────────────────────────────────────────────────────

async def _edge_tts_async(text: str, tmp_path: str) -> None:
    """
    Async helper that generates speech with edge-tts and saves to a file.

    Args:
        text:     Text to speak.
        tmp_path: Path to save the generated MP3 file.
    """
    communicate = edge_tts.Communicate(text, EDGE_VOICE)
    await communicate.save(tmp_path)


def _speak_edge(text: str) -> bool:
    """
    Speak text using edge-tts.

    Generates an MP3 via Microsoft's neural TTS and plays it
    using afplay (Mac built-in). Returns True on success,
    False on any failure so the caller can fall back to pyttsx3.

    Args:
        text: Clean ASCII text to speak.

    Returns:
        True on success, False on any failure.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name

        asyncio.run(_edge_tts_async(text, tmp_path))
        os.system(f"afplay {tmp_path}")
        os.unlink(tmp_path)
        return True

    except Exception as exc:
        print(f"[FocusBot] edge-tts failed: {exc} — falling back to Alex")
        return False


# ── Fallback Speaker ───────────────────────────────────────────────────────

def _speak_fallback(text: str, engine: pyttsx3.Engine | None) -> None:
    """
    Speak text using the pyttsx3 fallback engine (Alex voice).

    Args:
        text:   Clean ASCII text to speak.
        engine: Initialized pyttsx3 engine, or None to skip.
    """
    if engine is None:
        return
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass


# ── Main Speak Function ────────────────────────────────────────────────────

def speak(text: str, engine: pyttsx3.Engine | None) -> None:
    """
    Speak text aloud in a background thread.

    Tries edge-tts first (free, high quality). If it fails for any
    reason (no internet, etc.), automatically falls back to Alex
    via pyttsx3. Switches silently — no action needed from the user.

    Args:
        text:   The string to speak (emojis stripped automatically).
        engine: Initialized pyttsx3 fallback engine.
    """
    if not VOICE_ENABLED:
        return

    # Strip emojis and non-ASCII characters
    clean_text = re.sub(r"[^\x00-\x7F]+", "", text).strip()
    if not clean_text:
        return

    def _run() -> None:
        success = _speak_edge(clean_text)
        if not success:
            _speak_fallback(clean_text, engine)

    threading.Thread(target=_run, daemon=True).start()
