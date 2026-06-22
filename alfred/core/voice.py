"""
alfred.core.voice
------------------
Alfred's ears and mouth: wake word detection, speech-to-text, and
text-to-speech, all in one module because they share the same
microphone and the same threading.Event coordination handshake.

Three responsibilities live here:

1. Wake word detection (`start_wake_word`) — a background loop that
   listens in short 3-second bursts for the phrase "hey alfred" so the
   user never has to touch a button to start a conversation.
2. Speech-to-text (`init_listener`, `listen_once`, `start_listening`) —
   opens the microphone for a full utterance and transcribes it via
   Google's free speech recognition API.
3. Text-to-speech (`init_tts`, `speak`) — speaks Alfred's replies aloud,
   preferring Microsoft's free neural voices (edge-tts) and silently
   falling back to the offline pyttsx3/Alex voice if there's no
   internet connection.

Coordination: both the wake word loop and the full listening session
want exclusive use of the microphone. They share a single
`threading.Event` (the "active flag"). The wake word loop only opens
the mic when the flag is clear; `start_listening` sets the flag for
the duration of its own recording so the two never collide.
"""

import asyncio
import audioop
import math
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Callable

import edge_tts
import pyttsx3
import speech_recognition as sr

from alfred.config.settings import MIC_DEVICE_NAME, VOICE_ENABLED

# ── Wake Word Configuration ──────────────────────────────────────────────────
WAKE_PHRASE: str = "hey alfred"
# Audible "I heard you" cue played the instant the wake word is detected,
# before Alfred starts listening for the actual command — mirrors Siri's
# confirmation beep. Generated once via a small offline script; see
# assets/ — no network or extra dependency needed to (re)create it.
CHIME_PATH: Path = Path(__file__).resolve().parents[2] / "assets" / "chime.wav"

# ── Listening (STT) Configuration ────────────────────────────────────────────
LISTEN_TIMEOUT: int = 5
PHRASE_TIME_LIMIT: int = 10
# How long a pause must last before a phrase is considered finished —
# mirrors speech_recognition.Recognizer's own default pause_threshold.
PHRASE_PAUSE_SECONDS: float = 0.8

# ── Live Audio Level (for personality.on_audio_level) ───────────────────────
# Raw RMS value treated as "full scale" (1.0) when normalizing chunk
# energy for the live level callback — tuned from real measurements:
# quiet-room ambient sits well under 500, clear speech directly at a
# laptop mic commonly peaks in the low thousands.
LEVEL_NORMALIZE_RMS: float = 3000.0
# Only fire the level callback every Nth audio chunk (~23ms each at
# 44.1kHz/1024-sample chunks) — frequent enough to look live, far
# cheaper than driving hardware at the raw ~43Hz chunk rate.
LEVEL_CALLBACK_STRIDE: int = 4

# ── Speaking (TTS) Configuration ─────────────────────────────────────────────
# GuyNeural-style British male voice — clean and natural, no API key needed.
EDGE_VOICE: str = "en-GB-RyanNeural"
# Offline fallback used only if edge-tts fails (e.g. no internet).
FALLBACK_VOICE: str = "com.apple.speech.synthesis.voice.Alex"
FALLBACK_RATE: int = 185


def _resolve_mic_device_index() -> int | None:
    """
    Resolve settings.MIC_DEVICE_NAME to a PyAudio device index.

    Looked up fresh on every call (rather than once at import time) so
    a device that's plugged in or renamed after the process starts is
    still picked up correctly on the next listen attempt.

    Returns:
        The index of the first microphone whose name contains
        MIC_DEVICE_NAME (case-insensitive), or None to use whatever the
        OS currently reports as the default input device — either
        because MIC_DEVICE_NAME is unset, or because no microphone
        matched it.
    """
    if not MIC_DEVICE_NAME:
        return None

    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        if MIC_DEVICE_NAME.lower() in name.lower():
            return index

    print(f"[Alfred] MIC_DEVICE_NAME '{MIC_DEVICE_NAME}' not found among available microphones; using system default.")
    return None


def _listen_with_level(
    recognizer: sr.Recognizer,
    source: sr.AudioSource,
    timeout: float,
    phrase_time_limit: float,
    on_level: Callable[[float], None] | None = None,
) -> sr.AudioData:
    """
    Record one phrase from an already-open microphone source, the same
    way `recognizer.listen()` does — except this also reports a live,
    normalized (0.0-1.0) volume level via `on_level` as audio comes in.

    This is the one shared mic-reading loop behind both wake word
    detection and full command capture (`listen_once`), which is what
    lets a single live signal drive the OLED waveform and the servo
    arm's bobbing in alfred.core.personality.on_audio_level — there's
    nowhere else audio chunks get read from the microphone.

    `recognizer.listen()` itself has no hook for reporting levels as it
    reads each chunk, so this reimplements its phrase-boundary logic
    directly: wait for energy to cross `recognizer.energy_threshold`
    (phrase start), then keep recording until ~0.8s of quiet follows
    (phrase end), bounded by `timeout` (max wait for a phrase to start)
    and `phrase_time_limit` (max total recording length).

    Args:
        recognizer: Initialized SpeechRecognition Recognizer — its
            `energy_threshold` decides what counts as "speaking".
        source: An already-entered `sr.Microphone` context.
        timeout: Max seconds to wait for a phrase to start.
        phrase_time_limit: Max seconds to record once a phrase starts.
        on_level: Optional callback invoked with a normalized 0.0-1.0
            volume level every few chunks while audio is being read.

    Returns:
        The recorded phrase as an AudioData object.

    Raises:
        sr.WaitTimeoutError: If no phrase started within `timeout`.
    """
    seconds_per_chunk = source.CHUNK / source.SAMPLE_RATE
    pause_chunks = max(int(math.ceil(PHRASE_PAUSE_SECONDS / seconds_per_chunk)), 1)
    timeout_chunks = int(math.ceil(timeout / seconds_per_chunk))
    phrase_chunks = int(math.ceil(phrase_time_limit / seconds_per_chunk))

    def _report(rms: int, chunk_index: int) -> None:
        if on_level is not None and chunk_index % LEVEL_CALLBACK_STRIDE == 0:
            on_level(min(rms / LEVEL_NORMALIZE_RMS, 1.0))

    # Wait for the phrase to start: keep reading until a chunk's energy
    # crosses the threshold, or we run out of patience.
    buffers = []
    for i in range(timeout_chunks):
        buf = source.stream.read(source.CHUNK)
        rms = audioop.rms(buf, source.SAMPLE_WIDTH)
        _report(rms, i)
        if rms > recognizer.energy_threshold:
            buffers.append(buf)
            break
    else:
        raise sr.WaitTimeoutError("listening timed out while waiting for phrase to start")

    # Phrase started — keep recording until enough consecutive quiet
    # chunks pass, or we hit the hard phrase length limit.
    quiet_run = 0
    for i in range(1, phrase_chunks):
        buf = source.stream.read(source.CHUNK)
        buffers.append(buf)
        rms = audioop.rms(buf, source.SAMPLE_WIDTH)
        _report(rms, i)

        if rms > recognizer.energy_threshold:
            quiet_run = 0
        else:
            quiet_run += 1
            if quiet_run >= pause_chunks:
                break

    return sr.AudioData(b"".join(buffers), source.SAMPLE_RATE, source.SAMPLE_WIDTH)


def play_chime() -> None:
    """
    Play the wake word confirmation chime in a background thread.

    Mirrors `speak`'s playback approach (`afplay`, non-blocking) but
    plays the static asset at CHIME_PATH instead of synthesizing
    speech. Silently does nothing if voice is disabled or the asset is
    missing, since a missing chime should never break wake word
    detection itself.
    """
    if not VOICE_ENABLED or not CHIME_PATH.exists():
        return

    def _run() -> None:
        os.system(f"afplay {CHIME_PATH}")

    threading.Thread(target=_run, daemon=True).start()


# =============================================================================
# Wake Word Detection
# =============================================================================

def start_wake_word(on_detected: Callable[[str], None], active_flag: threading.Event) -> None:
    """
    Start listening for the wake word ("hey alfred") in a background thread.

    Runs an infinite loop of short (4 second) listen bursts. Only attempts
    to open the microphone when `active_flag` is NOT set — that flag is
    owned by the full listening session (`start_listening`) so the wake
    word loop and a real conversation never fight over the microphone.

    The ambient noise threshold is calibrated once, before the loop
    starts, rather than on every burst. Recalibrating every ~4 seconds
    from a very short sample fights against `dynamic_energy_threshold`
    ever settling on a stable value — in practice that made the wake
    word noticeably less forgiving of timing than the manually-triggered
    full listening session (`listen_once`), which only calibrates once.

    Supports same-breath commands: if the burst transcribes to more
    than just the wake phrase (e.g. "hey alfred what's the weather"),
    everything after "hey alfred" is passed to `on_detected` as the
    command, so the caller can skip opening a second listening session.

    Args:
        on_detected: Callback fired with whatever text followed the
            wake phrase in the same utterance — an empty string if the
            user said only "hey alfred" with nothing else.
        active_flag: Shared Event, set to True while the main listening
            session has the microphone open.
    """
    def _listen() -> None:
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True

        device_index = _resolve_mic_device_index()
        try:
            with sr.Microphone(device_index=device_index) as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
            # A single noisy moment during calibration (a click, a fan
            # spike, the startup wave gesture) can otherwise lock in an
            # unreasonably high threshold for the entire process
            # lifetime — clamp it to a range normal speech can clear.
            recognizer.energy_threshold = min(recognizer.energy_threshold, 500)
        except Exception as exc:
            recognizer.energy_threshold = 300
            print(f"[Alfred] wake-word: calibration failed ({exc}), using default threshold")
        print(f"[Alfred] wake-word: listening on device_index={device_index}, energy_threshold={recognizer.energy_threshold:.0f}")

        while True:
            # Pause the wake-word loop entirely while a full session is active.
            if active_flag.is_set():
                active_flag.wait(timeout=0.5)
                continue

            try:
                with sr.Microphone(device_index=device_index) as source:
                    audio = _listen_with_level(recognizer, source, timeout=4, phrase_time_limit=4)

                # The main listener may have taken over while we were
                # recording this burst — discard it rather than racing.
                if active_flag.is_set():
                    continue

                text = recognizer.recognize_google(audio).lower()
                if WAKE_PHRASE in text:
                    play_chime()
                    command = text.split(WAKE_PHRASE, 1)[1].strip()
                    on_detected(command)

            except sr.WaitTimeoutError:
                pass
            except sr.UnknownValueError:
                pass
            except sr.RequestError as exc:
                print(f"[Alfred] wake-word: recognition service error: {exc}")
            except Exception as exc:
                print(f"[Alfred] wake-word: unexpected error: {type(exc).__name__}: {exc}")

    threading.Thread(target=_listen, daemon=True).start()


# =============================================================================
# Speech-to-Text (Listening)
# =============================================================================

def init_listener() -> tuple[sr.Recognizer, threading.Event]:
    """
    Initialize the speech recognizer and the shared active flag.

    The active flag is set while the main microphone session is open and
    cleared when listening finishes. The wake word detector checks this
    flag to avoid opening the mic at the same time.

    Returns:
        A tuple of (Recognizer, active_flag Event).
    """
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    active_flag = threading.Event()
    return recognizer, active_flag


def listen_once(recognizer: sr.Recognizer, on_level: Callable[[float], None] | None = None) -> str | None:
    """
    Listen for a single spoken phrase and return the transcribed text.

    Args:
        recognizer: Initialized SpeechRecognition Recognizer.
        on_level: Optional callback invoked with a normalized 0.0-1.0
            volume level as audio comes in — see `_listen_with_level`.
            Used by alfred.core.personality.on_audio_level to drive
            the OLED waveform and the servo arm's live bobbing while
            Alfred is actively listening.

    Returns:
        The transcribed text, or None if nothing was understood, the
        listen timed out, or the recognition service was unreachable.
    """
    try:
        with sr.Microphone(device_index=_resolve_mic_device_index()) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            # See start_wake_word's matching comment: a single noisy
            # moment during this 0.5s calibration can otherwise lock in
            # a threshold real speech can't clear.
            recognizer.energy_threshold = min(recognizer.energy_threshold, 500)
            audio = _listen_with_level(
                recognizer,
                source,
                timeout=LISTEN_TIMEOUT,
                phrase_time_limit=PHRASE_TIME_LIMIT,
                on_level=on_level,
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
    on_result: Callable[[str], None],
    on_listening: Callable[[], None],
    on_done: Callable[[], None],
    on_level: Callable[[float], None] | None = None,
    on_nothing_heard: Callable[[], None] | None = None,
) -> None:
    """
    Start listening for voice input in a background thread.

    Sets `active_flag` while the mic is open so the wake word detector
    pauses, then clears it when done — regardless of whether speech was
    successfully transcribed.

    Args:
        recognizer: Initialized SpeechRecognition Recognizer.
        active_flag: Shared Event used to block the wake word loop.
        on_result: Callback invoked with the transcribed text string,
            only fired if transcription succeeded.
        on_listening: Callback fired (no arguments) the moment the
            microphone opens — used to update UI/hardware state.
        on_done: Callback fired (no arguments) when listening ends,
            whether or not speech was recognized.
        on_level: Optional callback invoked with a normalized 0.0-1.0
            volume level as audio comes in — passed through to
            `listen_once`. See `_listen_with_level`.
        on_nothing_heard: Optional callback invoked (with no arguments)
            when listening ends with nothing transcribed — e.g. the
            user said only the wake word and then nothing, so Alfred
            still has something to say rather than going quiet.
    """
    def _listen() -> None:
        active_flag.set()       # block the wake word detector
        on_listening()
        text = listen_once(recognizer, on_level=on_level)
        on_done()
        active_flag.clear()     # release the wake word detector
        if text:
            on_result(text)
        elif on_nothing_heard is not None:
            on_nothing_heard()

    threading.Thread(target=_listen, daemon=True).start()


# =============================================================================
# Text-to-Speech (Speaking)
# =============================================================================

def init_tts() -> pyttsx3.Engine | None:
    """
    Initialize the pyttsx3 fallback TTS engine.

    Used only when edge-tts is unavailable (e.g. no internet connection).

    Returns:
        A configured pyttsx3 engine, or None if initialization fails.
    """
    try:
        engine = pyttsx3.init()
        engine.setProperty("voice", FALLBACK_VOICE)
        engine.setProperty("rate", FALLBACK_RATE)
        engine.setProperty("volume", 0.9)
        return engine
    except Exception as exc:
        print(f"[Alfred] TTS fallback init failed: {exc}")
        return None


async def _edge_tts_async(text: str, tmp_path: str) -> None:
    """
    Async helper that generates speech audio with edge-tts and saves it.

    Args:
        text: Text to synthesize.
        tmp_path: Filesystem path to write the generated MP3 to.
    """
    communicate = edge_tts.Communicate(text, EDGE_VOICE)
    await communicate.save(tmp_path)


def _speak_edge(text: str) -> bool:
    """
    Speak text aloud using edge-tts (Microsoft's free neural voices).

    Generates an MP3 to a temporary file and plays it with `afplay`
    (Mac's built-in player). Any failure — no internet, afplay missing,
    etc. — is swallowed and reported via the return value so the caller
    can fall back to the offline pyttsx3 engine.

    Args:
        text: Clean ASCII text to speak (emoji already stripped).

    Returns:
        True if playback completed, False on any failure.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name

        asyncio.run(_edge_tts_async(text, tmp_path))
        os.system(f"afplay {tmp_path}")
        os.unlink(tmp_path)
        return True

    except Exception as exc:
        print(f"[Alfred] edge-tts failed: {exc} — falling back to Alex")
        return False


def _speak_fallback(text: str, engine: pyttsx3.Engine | None) -> None:
    """
    Speak text aloud using the offline pyttsx3 fallback engine.

    Args:
        text: Clean ASCII text to speak.
        engine: Initialized pyttsx3 engine, or None to skip silently.
    """
    if engine is None:
        return
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass


def speak(text: str, engine: pyttsx3.Engine | None) -> None:
    """
    Speak text aloud in a background thread.

    Tries edge-tts first (free, high quality, needs internet). If that
    fails for any reason, silently falls back to the offline pyttsx3
    Alex voice — no action needed from the caller either way.

    Args:
        text: The string to speak. Emoji and other non-ASCII characters
            are stripped automatically since neither voice engine
            handles them well.
        engine: Initialized pyttsx3 fallback engine (see `init_tts`).
    """
    if not VOICE_ENABLED:
        return

    # Strip emoji/non-ASCII before handing text to either voice engine.
    clean_text = re.sub(r"[^\x00-\x7F]+", "", text).strip()
    if not clean_text:
        return

    def _run() -> None:
        success = _speak_edge(clean_text)
        if not success:
            _speak_fallback(clean_text, engine)

    threading.Thread(target=_run, daemon=True).start()
