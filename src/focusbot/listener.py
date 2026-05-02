"""
listener.py

Voice input module for alfred.ai.

Listens for speech via the microphone and transcribes it using
Google Speech Recognition. Uses a shared threading.Event flag to
coordinate with the wake word detector so they never conflict.
"""

import threading
import speech_recognition as sr

LISTEN_TIMEOUT    = 5
PHRASE_TIME_LIMIT = 10


def init_listener() -> tuple[sr.Recognizer, threading.Event]:
    """
    Initialize the speech recognizer and the shared active flag.

    The active flag is set while the main mic is open and cleared
    when listening finishes. The wake word detector checks this flag
    to avoid opening the mic at the same time.

    Returns:
        Tuple of (Recognizer, active_flag Event).
    """
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    active_flag = threading.Event()
    return recognizer, active_flag


def listen_once(recognizer: sr.Recognizer) -> str | None:
    """
    Listen for a single spoken phrase and return transcribed text.

    Args:
        recognizer: Initialized SpeechRecognition Recognizer.

    Returns:
        Transcribed text string, or None on failure.
    """
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(
                source,
                timeout=LISTEN_TIMEOUT,
                phrase_time_limit=PHRASE_TIME_LIMIT,
            )
        return recognizer.recognize_google(audio)

    except sr.WaitTimeoutError:
        return None
    except sr.UnknownValueError:
        return None
    except sr.RequestError as exc:
        print(f"[Alfred] Speech recognition error: {exc}")
        return None
    except Exception as exc:
        print(f"[Alfred] Listener error: {exc}")
        return None


def start_listening(
    recognizer: sr.Recognizer,
    active_flag: threading.Event,
    on_result,
    on_listening,
    on_done,
) -> None:
    """
    Start listening for voice input in a background thread.

    Sets active_flag while the mic is open so the wake word detector
    pauses. Clears it when done.

    Args:
        recognizer:   Initialized SpeechRecognition Recognizer.
        active_flag:  Shared threading.Event to block the wake word loop.
        on_result:    Callback(text: str) called with transcribed speech.
        on_listening: Callback() fired when mic opens.
        on_done:      Callback() fired when listening ends.
    """
    def _listen() -> None:
        active_flag.set()       # block wake word detector
        on_listening()
        text = listen_once(recognizer)
        on_done()
        active_flag.clear()     # release wake word detector
        if text:
            on_result(text)

    threading.Thread(target=_listen, daemon=True).start()
    