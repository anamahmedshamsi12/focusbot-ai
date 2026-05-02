"""
wakeword.py

Wake word detection for alfred.ai.

Listens in short bursts for "hey alfred". When detected, sets a
shared Event flag so the main listener knows to hand off control,
then fires the on_detected callback to open the full mic session.
"""

import threading
import speech_recognition as sr

WAKE_PHRASE = "hey alfred"


def start_wake_word(on_detected, active_flag: threading.Event) -> None:
    """
    Start listening for the wake word in a background thread.

    Only runs when active_flag is NOT set (i.e. Alfred is not already
    listening). This prevents the wake word loop and the main listener
    from fighting over the microphone.

    Args:
        on_detected:  Callback fired when wake word is heard.
        active_flag:  Threading Event set to True while main mic is open.
    """
    def _listen() -> None:
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True

        while True:
            # Wait while the main listener is active
            if active_flag.is_set():
                active_flag.wait(timeout=0.5)
                continue

            try:
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.3)
                    audio = recognizer.listen(source, timeout=3, phrase_time_limit=3)

                # Don't process if main listener took over while we were recording
                if active_flag.is_set():
                    continue

                text = recognizer.recognize_google(audio).lower()
                if WAKE_PHRASE in text:
                    on_detected()

            except sr.WaitTimeoutError:
                pass
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                pass
            except Exception:
                pass

    threading.Thread(target=_listen, daemon=True).start()
