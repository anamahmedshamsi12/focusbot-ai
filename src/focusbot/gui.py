"""
gui.py

Tkinter GUI for alfred.ai.

FocusBotApp is the main application window. It wires together the
assistant, reminders, voice, and listener modules into a single chat
interface with a mode toggle, quick-action buttons, mic input, and
a live status bar.
"""

import threading
import tkinter as tk
from tkinter import scrolledtext

import pyttsx3

from focusbot.assistant import (
    FOCUS_MODE_PROMPT,
    GENERAL_PROMPT,
    ask_alfred,
    create_client,
)
from focusbot.config import FOCUS_MINUTES
from focusbot.listener import init_listener, start_listening
from focusbot.memory import add_note, add_task, load_memory, update_name
from focusbot.wakeword import start_wake_word
from focusbot.reminders import (
    detect_intent,
    parse_reminder,
    set_reminder,
    start_focus_timer,
)
from focusbot.voice import init_tts, speak


class FocusBotApp:
    """
    Main application window for alfred.ai.

    Responsibilities:
    - Build and manage all tkinter widgets
    - Route user messages to the correct handler (AI, timer, reminder)
    - Provide thread-safe display_message and update_status callbacks
      used by reminders.py and other background threads
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("alfred.ai")
        self.root.geometry("600x700")
        self.root.configure(bg="#1a1a2e")
        self.root.resizable(True, True)

        # State
        self.conversation_history: list[dict] = []
        self.focus_active: bool = False
        self.focus_mode: bool   = False
        self.is_listening: bool = False
        self.memory: dict       = load_memory()

        # External dependencies
        self.tts_engine: pyttsx3.Engine | None = init_tts()
        self.recognizer, self.active_flag = init_listener()
        self.client = create_client()

        self._build_ui()
        self._welcome()
        start_wake_word(self._on_wake_word, self.active_flag)

    # UI Construction

    def _build_ui(self) -> None:
        """Construct all tkinter widgets and lay them out."""
        self._build_title_bar()
        self._build_quick_buttons()
        self._build_chat_display()
        self._build_input_area()
        self._build_status_bar()

    def _build_title_bar(self) -> None:
        frame = tk.Frame(self.root, bg="#16213e", pady=10)
        frame.pack(fill="x")

        tk.Label(
            frame, text="alfred.ai",
            font=("Helvetica", 22, "bold"),
            bg="#16213e", fg="#00d4ff",
        ).pack(side="left", padx=20)

        tk.Label(
            frame, text="AI Assistant",
            font=("Helvetica", 11),
            bg="#16213e", fg="#888888",
        ).pack(side="left")

        self.mode_btn = tk.Button(
            frame,
            text="Focus Mode: OFF",
            command=self._toggle_mode,
            bg="#0f3460", fg="#888888",
            font=("Helvetica", 10),
            relief="flat", padx=12, pady=4, cursor="hand2",
        )
        self.mode_btn.pack(side="right", padx=5)

        tk.Button(
            frame,
            text="Settings",
            command=self._open_settings,
            bg="#0f3460", fg="#888888",
            font=("Helvetica", 10),
            relief="flat", padx=12, pady=4, cursor="hand2",
        ).pack(side="right", padx=5)

    def _build_quick_buttons(self) -> None:
        frame = tk.Frame(self.root, bg="#1a1a2e", pady=8)
        frame.pack(fill="x", padx=15)

        buttons = [
            ("Focus 25min", self._quick_focus),
            ("Breakdown",   self._quick_breakdown),
            ("Routine",     self._quick_routine),
            ("Stop Timer",  self._stop_focus),
        ]
        for label, cmd in buttons:
            tk.Button(
                frame, text=label, command=cmd,
                bg="#0f3460", fg="white",
                font=("Helvetica", 10),
                relief="flat", padx=10, pady=5, cursor="hand2",
                activebackground="#e94560", activeforeground="white",
            ).pack(side="left", padx=4)

    def _build_chat_display(self) -> None:
        frame = tk.Frame(self.root, bg="#1a1a2e")
        frame.pack(fill="both", expand=True, padx=15, pady=(0, 5))

        self.chat_display = scrolledtext.ScrolledText(
            frame,
            wrap=tk.WORD,
            bg="#0d0d1a", fg="#e0e0e0",
            font=("Helvetica", 12),
            relief="flat", padx=12, pady=10,
            state="disabled", insertbackground="white",
        )
        self.chat_display.pack(fill="both", expand=True)

        self.chat_display.tag_configure("bot_name",  foreground="#00d4ff", font=("Helvetica", 12, "bold"))
        self.chat_display.tag_configure("bot_text",  foreground="#e0e0e0", font=("Helvetica", 12))
        self.chat_display.tag_configure("user_name", foreground="#ff6b9d", font=("Helvetica", 12, "bold"))
        self.chat_display.tag_configure("user_text", foreground="#cccccc", font=("Helvetica", 12))
        self.chat_display.tag_configure("system",    foreground="#888888", font=("Helvetica", 10, "italic"))

    def _build_input_area(self) -> None:
        frame = tk.Frame(self.root, bg="#16213e", pady=10)
        frame.pack(fill="x", padx=15, pady=(0, 5))

        self.mic_btn = tk.Button(
            frame, text="🎙",
            command=self._on_mic,
            bg="#0f3460", fg="white",
            font=("Helvetica", 14),
            relief="flat", padx=10, pady=6, cursor="hand2",
            activebackground="#e94560", activeforeground="white",
        )
        self.mic_btn.pack(side="left", padx=(0, 8))

        self.input_field = tk.Entry(
            frame,
            bg="#0d0d1a", fg="white",
            font=("Helvetica", 13),
            relief="flat", insertbackground="white",
        )
        self.input_field.pack(side="left", fill="x", expand=True, ipady=10, padx=(0, 8))
        self.input_field.bind("<Return>", self._on_send)
        self.input_field.focus()

        tk.Button(
            frame, text="Send",
            command=self._on_send,
            bg="#e94560", fg="white",
            font=("Helvetica", 12, "bold"),
            relief="flat", padx=16, pady=8, cursor="hand2",
        ).pack(side="right")

    def _build_status_bar(self) -> None:
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(
            self.root,
            textvariable=self.status_var,
            bg="#0d0d1a", fg="#555555",
            font=("Helvetica", 10),
            anchor="w", padx=10,
        ).pack(fill="x")

    # Thread-safe UI Callbacks

    def display_message(self, sender: str, message: str) -> None:
        """
        Append a message to the chat display.
        Safe to call from any thread.

        Args:
            sender: 'Alfred', 'You', or anything else shown as system text.
            message: The message body to display.
        """
        def _update() -> None:
            self.chat_display.configure(state="normal")
            if sender == "Alfred":
                self.chat_display.insert("end", "\nAlfred  ", "bot_name")
                self.chat_display.insert("end", f"\n{message}\n", "bot_text")
            elif sender == "You":
                self.chat_display.insert("end", "\nYou  ", "user_name")
                self.chat_display.insert("end", f"\n{message}\n", "user_text")
            else:
                self.chat_display.insert("end", f"\n{message}\n", "system")
            self.chat_display.configure(state="disabled")
            self.chat_display.see("end")

        self.root.after(0, _update)

    def update_status(self, text: str) -> None:
        """
        Update the status bar text.
        Safe to call from any thread.

        Args:
            text: Status string to display.
        """
        self.root.after(0, lambda: self.status_var.set(text))

    # Wake Word

    def _on_wake_word(self) -> None:
        """
        Called when 'hey alfred' is detected.
        Automatically triggers the mic as if the user clicked the button.
        """
        if self.is_listening:
            return
        self.display_message("System", "Wake word detected - listening...")
        self._on_mic()

    # Voice Input

    def _on_mic(self) -> None:
        """Called when the mic button is clicked. Starts listening."""
        if self.is_listening:
            return

        start_listening(
            recognizer=self.recognizer,
            active_flag=self.active_flag,
            on_listening=self._on_listening,
            on_result=self._on_voice_result,
            on_done=self._on_listening_done,
        )

    def _on_listening(self) -> None:
        """Called when the mic opens. Updates UI to show listening state."""
        self.is_listening = True
        self.root.after(0, lambda: self.mic_btn.config(bg="#e94560", text="🔴"))
        self.update_status("Listening...")

    def _on_listening_done(self) -> None:
        """Called when listening finishes. Resets mic button."""
        self.is_listening = False
        self.root.after(0, lambda: self.mic_btn.config(bg="#0f3460", text="🎙"))
        self.update_status("Ready")

    def _on_voice_result(self, text: str) -> None:
        """
        Called when speech is successfully transcribed.

        Args:
            text: Transcribed speech string.
        """
        self.display_message("You", text)
        threading.Thread(target=self._process_message, args=(text,), daemon=True).start()

    # Message Routing

    def _on_send(self, event: tk.Event | None = None) -> None:
        """Called when the user presses Enter or clicks Send."""
        text = self.input_field.get().strip()
        if not text:
            return
        self.input_field.delete(0, tk.END)
        self.display_message("You", text)
        threading.Thread(target=self._process_message, args=(text,), daemon=True).start()

    def _process_message(self, text: str) -> None:
        """
        Route a user message to the correct handler based on detected intent.
        Runs in a background thread to keep the UI responsive.

        Args:
            text: The user's raw input string.
        """
        self.update_status("Alfred is thinking...")
        intent = detect_intent(text)

        # Check for memory commands
        low = text.lower()
        if "my name is" in low:
            name = text.lower().split("my name is")[-1].strip().split()[0]
            update_name(self.memory, name)
        elif "remember that" in low:
            note = text.lower().split("remember that")[-1].strip()
            add_note(self.memory, note)
        elif any(w in low for w in ["i need to", "i have to", "i should"]):
            add_task(self.memory, text.strip())

        if intent == "stop":
            self.focus_active = False
            self.display_message("Alfred", "Focus session stopped. Good effort!")
            speak("Focus session stopped. Good effort!", self.tts_engine)
            self.update_status("Ready")

        elif intent == "focus":
            reply = ask_alfred(text, self.conversation_history, self.client, self._active_prompt(), self.memory)
            self.display_message("Alfred", reply)
            speak(reply, self.tts_engine)
            start_focus_timer(FOCUS_MINUTES, self)

        elif intent == "reminder":
            minutes = parse_reminder(text)
            reply = ask_alfred(text, self.conversation_history, self.client, self._active_prompt(), self.memory)
            self.display_message("Alfred", reply)
            speak(reply, self.tts_engine)
            if minutes:
                set_reminder(minutes, text, self)
                self.display_message("System", f"Reminder set for {minutes} minutes from now.")
            else:
                self.display_message("System", "Could not find a time. Try: Remind me in 20 minutes to...")
            self.update_status("Ready")

        else:
            reply = ask_alfred(text, self.conversation_history, self.client, self._active_prompt(), self.memory)
            self.display_message("Alfred", reply)
            speak(reply, self.tts_engine)
            self.update_status("Ready")

    # Mode Toggle

    def _toggle_mode(self) -> None:
        """
        Switch between General Mode and ADHD Focus Mode.
        Clears conversation history on switch so the AI stays in context.
        """
        self.focus_mode = not self.focus_mode
        self.conversation_history = []

        if self.focus_mode:
            self.mode_btn.config(text="Focus Mode: ON", fg="#00d4ff")
            self.display_message("System", "Switched to Focus Mode. Conversation reset.")
            self.display_message("Alfred", "Focus Mode on. I will keep things short and break tasks down. What are we working on?")
        else:
            self.mode_btn.config(text="Focus Mode: OFF", fg="#888888")
            self.display_message("System", "Switched to General Mode. Conversation reset.")
            self.display_message("Alfred", "General mode on. I can help with anything now. What is on your mind?")

    def _active_prompt(self) -> str:
        """Return the system prompt for whichever mode is currently active."""
        return FOCUS_MODE_PROMPT if self.focus_mode else GENERAL_PROMPT

    # Quick Action Buttons

    def _quick_focus(self) -> None:
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "Start a 25-minute focus session")
        self._on_send()

    def _quick_breakdown(self) -> None:
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "I need help breaking down a task")
        self._on_send()

    def _quick_routine(self) -> None:
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "Help me with my morning routine")
        self._on_send()

    def _stop_focus(self) -> None:
        self.focus_active = False
        self.update_status("Ready")
        self.display_message("Alfred", "Timer stopped. That is okay, every minute counts!")

    # Settings Panel

    def _open_settings(self) -> None:
        """Open the settings window."""
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("400x420")
        win.configure(bg="#1a1a2e")
        win.resizable(False, False)

        tk.Label(
            win, text="Settings",
            font=("Helvetica", 16, "bold"),
            bg="#1a1a2e", fg="#00d4ff",
        ).pack(pady=(20, 15))

        # Name field
        tk.Label(win, text="Your Name", bg="#1a1a2e", fg="#888888", font=("Helvetica", 11)).pack(anchor="w", padx=30)
        name_var = tk.StringVar(value=self.memory.get("name") or "")
        name_entry = tk.Entry(win, textvariable=name_var, bg="#0d0d1a", fg="white", font=("Helvetica", 12), relief="flat", insertbackground="white")
        name_entry.pack(fill="x", padx=30, ipady=8, pady=(4, 14))

        # Focus timer length
        tk.Label(win, text="Focus Timer (minutes)", bg="#1a1a2e", fg="#888888", font=("Helvetica", 11)).pack(anchor="w", padx=30)
        timer_var = tk.IntVar(value=self.memory.get("preferences", {}).get("focus_minutes", 25))
        timer_spin = tk.Spinbox(win, from_=5, to=90, increment=5, textvariable=timer_var, bg="#0d0d1a", fg="white", font=("Helvetica", 12), relief="flat", buttonbackground="#0f3460", width=5)
        timer_spin.pack(anchor="w", padx=30, ipady=6, pady=(4, 14))

        # Voice toggle
        tk.Label(win, text="Voice Output", bg="#1a1a2e", fg="#888888", font=("Helvetica", 11)).pack(anchor="w", padx=30)
        voice_var = tk.BooleanVar(value=self.memory.get("preferences", {}).get("voice_enabled", True))
        tk.Checkbutton(
            win, text="Enabled", variable=voice_var,
            bg="#1a1a2e", fg="white", selectcolor="#0f3460",
            font=("Helvetica", 11), activebackground="#1a1a2e",
        ).pack(anchor="w", padx=30, pady=(4, 14))

        # Memory summary
        notes = self.memory.get("notes", [])
        tasks = self.memory.get("tasks", [])
        summary = f"{len(notes)} note(s), {len(tasks)} task(s) stored"
        tk.Label(win, text=f"Memory: {summary}", bg="#1a1a2e", fg="#555555", font=("Helvetica", 10)).pack(anchor="w", padx=30)

        # Clear memory button
        def _clear_memory() -> None:
            from focusbot.memory import clear_memory
            clear_memory(self.memory)
            self.display_message("System", "Memory cleared.")
            win.destroy()

        tk.Button(
            win, text="Clear All Memory",
            command=_clear_memory,
            bg="#3a0a0a", fg="#ff6b6b",
            font=("Helvetica", 10),
            relief="flat", padx=10, pady=4, cursor="hand2",
        ).pack(anchor="w", padx=30, pady=(4, 20))

        # Save button
        def _save() -> None:
            name = name_var.get().strip()
            if name:
                update_name(self.memory, name)

            if "preferences" not in self.memory:
                self.memory["preferences"] = {}
            self.memory["preferences"]["focus_minutes"] = timer_var.get()
            self.memory["preferences"]["voice_enabled"] = voice_var.get()

            from focusbot.memory import save_memory
            save_memory(self.memory)
            self.display_message("System", "Settings saved.")
            win.destroy()

        tk.Button(
            win, text="Save",
            command=_save,
            bg="#e94560", fg="white",
            font=("Helvetica", 12, "bold"),
            relief="flat", padx=20, pady=8, cursor="hand2",
        ).pack(pady=10)

    # Welcome Message

    def _welcome(self) -> None:
        """Display and speak the initial greeting when the app launches."""
        name = self.memory.get("name")
        greeting = f"Hey {name}!" if name else "Hey!"
        message = (
            f"{greeting} I am Alfred, your AI desk assistant.\n\n"
            "I can help with pretty much anything - questions, tasks,\n"
            "writing, ideas, or just a chat.\n\n"
            "Need ADHD focus support? Hit the Focus Mode button\n"
            "in the top right to switch modes anytime.\n\n"
            "Click the mic button or type to get started!"
        )
        self.display_message("Alfred", message)
        speak(f"{greeting} I am Alfred. Click the mic or type to get started!", self.tts_engine)
        